#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using Page = uint64_t;
using Placement = std::set<Page>;
constexpr int NONE = -1;
struct Config {
    size_t warmup=200000, train=500000, eval=500000;
    size_t cache_kib=1024, ways=8, rob=192, width=4, mlp=16;
    double core_ns=0.333333333333, hit_ns=4, fast_ns=80, slow_ns=250;
    double pac_window_ns=20000000, pac_alpha=1, pac_k_dram_ns=0, pac_k_cxl_ns=0;
};
// Standard little-endian 64-byte ChampSim input_instr, decoded explicitly.
struct Instruction {
    std::array<uint8_t,2> dst{};
    std::array<uint8_t,4> src{};
    std::array<uint64_t,2> stores{};
    std::array<uint64_t,4> loads{};
};
uint64_t u64(const unsigned char* b) {
    uint64_t n=0;
    for(int i=0;i<8;++i) n |= uint64_t(b[i]) << (8*i);
    return n;
}
Instruction read(std::istream& in) {
    unsigned char b[64];
    if(!in.read(reinterpret_cast<char*>(b),64))
        throw std::runtime_error("Trace too short or truncated; need warmup+train+eval records");
    if(b[8]>1 || b[9]>1) throw std::runtime_error("Invalid standard ChampSim branch fields");
    Instruction result;
    std::copy(b+10,b+12,result.dst.begin());
    std::copy(b+12,b+16,result.src.begin());
    for(int i=0;i<2;++i) result.stores[i]=u64(b+16+8*i);
    for(int i=0;i<4;++i) result.loads[i]=u64(b+32+8*i);
    return result;
}
struct Cache {
    size_t ways;
    uint64_t clock=0;
    struct Line { uint64_t tag=0, stamp=0; bool valid=false; };
    std::vector<std::vector<Line>> sets;
    explicit Cache(const Config& c): ways(c.ways),
        sets(c.cache_kib*1024/(64*c.ways),std::vector<Line>(c.ways)) {}
    bool miss(uint64_t address) {
        uint64_t line=address/64;
        auto& set=sets[line%sets.size()];
        ++clock;
        for(auto& e:set) if(e.valid && e.tag==line) {e.stamp=clock;return false;}
        auto victim=std::min_element(set.begin(),set.end(),[](const Line&a,const Line&b){
            return a.stamp<b.stamp;
        });
        *victim={line,clock,true};
        return true;
    }
};
struct Node {
    std::vector<int> deps;
    std::vector<Page> misses;
    size_t hits=0;
    std::vector<bool> miss_loads;
};
struct Segment {
    std::vector<Node> nodes;
    std::unordered_map<Page,uint64_t> accesses, misses;
    std::unordered_map<Page,uint64_t> load_misses;
};
Segment load(std::istream& in,size_t count,Cache& cache,bool retain) {
    Segment segment;
    std::array<int,256> producers; producers.fill(NONE);
    std::unordered_map<uint64_t,int> last_store,last_access;
    if(retain) segment.nodes.reserve(count);
    for(size_t i=0;i<count;++i) {
        auto instruction=read(in);
        Node node;
        auto dependency=[&](int predecessor){
            if(predecessor!=NONE) node.deps.push_back(predecessor);
        };
        if(retain) for(auto r:instruction.src) if(r) dependency(producers[r]);
        auto access=[&](uint64_t address,bool store){
            if(!address) return; // Zero is the format's absent-operand sentinel.
            uint64_t line=address/64;
            Page page=address/4096;
            bool miss=cache.miss(address);
            if(!retain) return;
            ++segment.accesses[page];
            if(miss) {
                node.misses.push_back(page);node.miss_loads.push_back(!store);
                ++segment.misses[page];
                if(!store) ++segment.load_misses[page];
            }
            else ++node.hits;
            auto previous=last_store.find(line);
            if(previous!=last_store.end() && previous->second!=int(i)) dependency(previous->second);
            if(store) {
                auto access_it=last_access.find(line);
                if(access_it!=last_access.end() && access_it->second!=int(i)) dependency(access_it->second);
                last_store[line]=int(i);
            }
            last_access[line]=int(i);
        };
        for(auto address:instruction.loads) access(address,false);
        for(auto address:instruction.stores) access(address,true);
        if(retain) {
            for(auto r:instruction.dst) if(r) producers[r]=int(i);
            std::sort(node.deps.begin(),node.deps.end());
            node.deps.erase(std::unique(node.deps.begin(),node.deps.end()),node.deps.end());
            segment.nodes.push_back(std::move(node));
        }
    }
    return segment;
}
struct Request { double start,end; Page page; bool dram; };
struct Timing {
    double total=0;
    std::unordered_map<Page,double> criticality;
    std::vector<Request> requests;
};
Timing replay(const Segment& segment,const Placement& fast,const Config& c,bool profile=false,bool collect=false) {
    size_t n=segment.nodes.size();
    std::vector<double> finish(n),duration(n),time(2*n);
    std::vector<int> retire_owner(n);
    using Edge=std::pair<size_t,double>;
    std::vector<std::vector<Edge>> deps;
    if(profile) deps.resize(2*n);
    using Slot=std::pair<double,int>;
    std::priority_queue<Slot,std::vector<Slot>,std::greater<Slot>> slots;
    for(size_t j=0;j<c.mlp;++j) slots.push({0,NONE});
    Timing result;
    int retire=NONE;
    for(size_t i=0;i<n;++i) {
        const auto& node=segment.nodes[i];
        double dispatch=0;
        auto admit=[&](size_t p,double weight){
            dispatch=std::max(dispatch,time[p]+weight);
            if(profile) deps[2*i].push_back({p,weight});
        };
        if(i>0) admit(2*(i-1),0);
        if(i>=c.width) admit(2*(i-c.width),c.core_ns);
        if(i>=c.rob) admit(2*size_t(retire_owner[i-c.rob])+1,0);
        time[2*i]=dispatch;
        duration[i]=c.core_ns+node.hits*c.hit_ns;
        for(Page page:node.misses) duration[i]+=fast.count(page)?c.fast_ns:c.slow_ns;
        double begin=dispatch;
        if(profile) deps[2*i+1].push_back({2*i,duration[i]});
        auto depend=[&](int p){
            if(p!=NONE) {begin=std::max(begin,finish[p]);
                if(profile) deps[2*i+1].push_back({2*size_t(p)+1,duration[i]});}
        };
        for(int p:node.deps) depend(p);
        Slot slot{0,NONE};
        if(!node.misses.empty()) {slot=slots.top();slots.pop();depend(slot.second);}
        finish[i]=begin+duration[i];
        if(collect) {
            double request_start=begin+c.core_ns+node.hits*c.hit_ns;
            for(size_t m=0;m<node.misses.size();++m) {
                Page page=node.misses[m];bool dram=fast.count(page)!=0;
                double end=request_start+(dram?c.fast_ns:c.slow_ns);
                if(node.miss_loads.empty() || node.miss_loads[m])
                    result.requests.push_back({request_start,end,page,dram});
                request_start=end;
            }
        }
        time[2*i+1]=finish[i];
        if(!node.misses.empty()) slots.push({finish[i],int(i)});
        if(retire==NONE || finish[i]>finish[retire]) retire=int(i);
        retire_owner[i]=retire;
        result.total=std::max(result.total,finish[i]);
    }
    if(profile) {
        // Reverse longest-path pass on the baseline schedule's dependency and
        // resource edges. Slack discounts each miss's possible latency saving.
        std::vector<double> latest(2*n,result.total);
        for(size_t index=2*n;index>0;--index) {
            size_t v=index-1;
            if(v%2) {
                size_t i=v/2;
                double slack=std::max(0.0,latest[v]-time[v]);
                for(Page page:segment.nodes[i].misses)
                    result.criticality[page]+=std::max(0.0,c.slow_ns-c.fast_ns-slack);
            }
            for(const auto& edge:deps[v]) latest[edge.first]=std::min(latest[edge.first],latest[v]-edge.second);
        }
    }
    return result;
}
struct PacWindow {
    size_t window; bool dram;
    uint64_t misses=0;
    double occupancy_ns=0,active_ns=0,mlp=0,stalls_ns=0,attributed_ns=0;
    std::unordered_map<Page,uint64_t> pages;
};
struct PacProfile {
    Timing scores;
    std::vector<PacWindow> windows;
};
PacProfile pac_profile(const Timing& timing,const Config& c) {
    // Reconstruct T1 = integral(outstanding tier requests dt), and
    // T2 = time(tier requests > 0). Requests crossing a window contribute
    // occupancy to both windows; counts are attributed at issue time.
    auto requests=timing.requests;
    std::sort(requests.begin(),requests.end(),[](const Request&a,const Request&b){
        if(a.start!=b.start) return a.start<b.start;
        return a.end<b.end;
    });
    std::map<std::pair<size_t,bool>,PacWindow> buckets;
    std::map<std::pair<size_t,bool>,double> union_end;
    for(const auto& r:requests) {
        if(!(r.end>r.start) || r.start<0 || !std::isfinite(r.end))
            throw std::runtime_error("Invalid request interval");
        double last_index=std::floor(std::nextafter(r.end,0.0)/c.pac_window_ns);
        if(last_index>1000000) throw std::runtime_error("Too many PAC windows; increase --pac-window-ns");
        size_t first=size_t(std::floor(r.start/c.pac_window_ns));
        size_t last=size_t(last_index);
        for(size_t w=first;w<=last;++w) {
            auto key=std::make_pair(w,r.dram);
            auto& bucket=buckets[key];bucket.window=w;bucket.dram=r.dram;
            double lo=std::max(r.start,w*c.pac_window_ns);
            double hi=std::min(r.end,(w+1)*c.pac_window_ns);
            bucket.occupancy_ns+=hi-lo;
            auto previous=union_end.find(key);
            double covered=previous==union_end.end()?lo:std::max(lo,previous->second);
            bucket.active_ns+=std::max(0.0,hi-covered);
            union_end[key]=previous==union_end.end()?hi:std::max(previous->second,hi);
            if(w==first) {++bucket.misses;++bucket.pages[r.page];}
        }
    }
    PacProfile result;
    for(auto& entry:buckets) {
        auto& b=entry.second;
        b.mlp=b.occupancy_ns/b.active_ns;
        double k=b.dram?(c.pac_k_dram_ns>0?c.pac_k_dram_ns:c.fast_ns):
            (c.pac_k_cxl_ns>0?c.pac_k_cxl_ns:c.slow_ns);
        b.stalls_ns=k*b.misses/b.mlp;
        for(const auto& p:b.pages) {
            double attributed=b.stalls_ns*double(p.second)/b.misses;
            b.attributed_ns+=attributed;
        }
        result.windows.push_back(b);
    }
    // Cooling applies to every known page each window, including idle ones.
    size_t current=0;
    std::map<Page,size_t> last_update;
    for(const auto& b:result.windows) {
        current=std::max(current,b.window);
        for(const auto& p:b.pages) {
            auto old=last_update.find(p.first);
            auto& score=result.scores.criticality[p.first];
            if(old!=last_update.end()) score*=std::pow(c.pac_alpha,double(b.window-old->second));
            score+=b.stalls_ns*double(p.second)/b.misses;
            last_update[p.first]=b.window;
        }
    }
    for(auto& p:result.scores.criticality)
        p.second*=std::pow(c.pac_alpha,double(current-last_update.at(p.first)));
    result.scores.total=timing.total;
    return result;
}
Placement rank(const Segment& train,const Timing& baseline,size_t capacity,bool critical) {
    std::vector<Page> pages;
    for(const auto& entry:train.misses) pages.push_back(entry.first);
    auto score=[&](Page p){auto it=baseline.criticality.find(p);return it==baseline.criticality.end()?0:it->second;};
    std::sort(pages.begin(),pages.end(),[&](Page a,Page b){
        if(critical && score(a)!=score(b)) return score(a)>score(b);
        if(train.misses.at(a)!=train.misses.at(b)) return train.misses.at(a)>train.misses.at(b);
        return a<b;
    });
    Placement result;
    for(size_t i=0;i<std::min(capacity,pages.size());++i) result.insert(pages[i]);
    return result;
}
size_t integer(const std::string& value) {
    if(value.empty() || value.find_first_not_of("0123456789")!=std::string::npos)
        throw std::runtime_error("Expected unsigned integer: "+value);
    auto parsed=std::stoull(value);
    if(parsed>std::numeric_limits<size_t>::max()) throw std::runtime_error("Integer too large");
    return size_t(parsed);
}
double positive(const std::string& value) {
    size_t used=0;double x=std::stod(value,&used);
    if(used!=value.size() || !std::isfinite(x) || x<=0) throw std::runtime_error("Expected positive finite latency");
    return x;
}
int main(int argc,char** argv) {
    try {
        Config c;
        std::string path,prefix="results/run";
        std::string criticality="pac";
        std::vector<size_t> capacities{16,64,256};
        for(int i=1;i<argc;++i) {
            std::string option=argv[i];
            if(option=="--help") {
                std::cout<<"trace_profiler --trace raw.bin [--out results/name] [--capacities 16,64,256]\n"
                    <<"  --warmup N --train N --eval N --cache-kib N --ways N\n"
                    <<"  --rob N --width N --mlp N --core-ns N --hit-ns N --dram-ns N --cxl-ns N\n";
                std::cout<<"  --criticality pac|slack --pac-window-ns N --pac-alpha N\n"
                    <<"  --pac-k-dram-ns N --pac-k-cxl-ns N\n";
                return 0;
            }
            if(i+1>=argc) throw std::runtime_error("Missing value for "+option);
            std::string value=argv[++i];
            if(option=="--trace") path=value;
            else if(option=="--out") prefix=value;
            else if(option=="--warmup") c.warmup=integer(value);
            else if(option=="--train") c.train=integer(value);
            else if(option=="--eval") c.eval=integer(value);
            else if(option=="--cache-kib") c.cache_kib=integer(value);
            else if(option=="--ways") c.ways=integer(value);
            else if(option=="--rob") c.rob=integer(value);
            else if(option=="--width") c.width=integer(value);
            else if(option=="--mlp") c.mlp=integer(value);
            else if(option=="--core-ns") c.core_ns=positive(value);
            else if(option=="--hit-ns") c.hit_ns=positive(value);
            else if(option=="--fast-ns" || option=="--dram-ns") c.fast_ns=positive(value);
            else if(option=="--slow-ns" || option=="--cxl-ns") c.slow_ns=positive(value);
            else if(option=="--criticality") criticality=value;
            else if(option=="--pac-window-ns") c.pac_window_ns=positive(value);
            else if(option=="--pac-alpha") {
                size_t used=0;c.pac_alpha=std::stod(value,&used);
                if(used!=value.size() || !std::isfinite(c.pac_alpha) || c.pac_alpha<0 || c.pac_alpha>1)
                    throw std::runtime_error("Require 0 <= pac-alpha <= 1");
            }
            else if(option=="--pac-k-dram-ns") c.pac_k_dram_ns=positive(value);
            else if(option=="--pac-k-cxl-ns") c.pac_k_cxl_ns=positive(value);
            else if(option=="--capacities") {
                capacities.clear();size_t pos=0;
                do {auto end=value.find(',',pos);capacities.push_back(integer(value.substr(pos,end-pos)));
                    if(end==std::string::npos) break;
                    pos=end+1;
                }while(true);
            }else throw std::runtime_error("Unknown option: "+option);
        }
        if(path.empty()) throw std::runtime_error("--trace is required");
        if(criticality!="pac" && criticality!="slack") throw std::runtime_error("criticality must be pac or slack");
        if(!c.train || !c.eval || c.train>size_t(std::numeric_limits<int>::max()) || c.eval>size_t(std::numeric_limits<int>::max()) ||
           !c.cache_kib || c.cache_kib>1048576 || !c.ways || c.ways>1024 ||
           c.cache_kib*1024%(64*c.ways)!=0 || !c.rob || !c.width || !c.mlp ||
           c.mlp>1048576 || c.slow_ns<c.fast_ns)
            throw std::runtime_error("Invalid model sizes/latencies");
        std::ifstream input(path,std::ios::binary);
        if(!input) throw std::runtime_error("Cannot open "+path);
        Cache cache(c);
        load(input,c.warmup,cache,false);
        auto train=load(input,c.train,cache,true);
        auto eval=load(input,c.eval,cache,true);
        bool use_pac=criticality=="pac";
        auto training_timing=replay(train,{},c,!use_pac,use_pac);
        PacProfile pac;
        if(use_pac) pac=pac_profile(training_timing,c);
        auto training_baseline=use_pac?pac.scores:training_timing;
        Segment ranking;
        ranking.misses=use_pac?train.load_misses:train.misses;
        auto eval_baseline=replay(eval,{},c);
        std::ofstream summary(prefix+".csv"),pages(prefix+"_pages.csv"),metadata(prefix+"_config.txt");
        if(!summary || !pages || !metadata) throw std::runtime_error("Cannot write output; create output directory first");
        metadata<<std::setprecision(17)<<"trace="<<path<<"\nwarmup="<<c.warmup<<"\ntrain="<<c.train<<"\neval="<<c.eval
            <<"\ncache_kib="<<c.cache_kib<<"\nways="<<c.ways<<"\nrob="<<c.rob<<"\nwidth="<<c.width<<"\nmlp="<<c.mlp
            <<"\ncore_ns="<<c.core_ns<<"\nhit_ns="<<c.hit_ns<<"\nfast_ns="<<c.fast_ns<<"\nslow_ns="<<c.slow_ns
            <<"\ncriticality="<<criticality<<"\nfrequency_domain="<<(use_pac?"load_misses":"all_misses")
            <<"\npac_window_ns="<<c.pac_window_ns<<"\npac_alpha="<<c.pac_alpha
            <<"\npac_k_dram_ns="<<(c.pac_k_dram_ns>0?c.pac_k_dram_ns:c.fast_ns)
            <<"\npac_k_cxl_ns="<<(c.pac_k_cxl_ns>0?c.pac_k_cxl_ns:c.slow_ns)<<'\n';
        if(use_pac) {
            std::ofstream windows(prefix+"_pac_windows.csv");
            if(!windows) throw std::runtime_error("Cannot write PAC windows");
            windows<<"window,tier,load_misses,occupancy_ns,active_ns,measured_mlp,estimated_stalls_ns,attributed_ns\n";
            for(const auto& b:pac.windows) windows<<std::setprecision(17)<<b.window<<','<<(b.dram?"DRAM":"CXL")
                <<','<<b.misses<<','<<b.occupancy_ns<<','<<b.active_ns<<','<<b.mlp<<','<<b.stalls_ns<<','<<b.attributed_ns<<'\n';
        }
        pages<<"page,training_accesses,training_misses,training_load_misses,criticality_ns,evaluation_misses\n";
        std::vector<Page> sorted;
        for(const auto& p:ranking.misses) sorted.push_back(p.first);
        std::sort(sorted.begin(),sorted.end());
        for(Page p:sorted) pages<<p<<','<<train.accesses[p]<<','<<train.misses[p]<<','<<train.load_misses[p]<<','
            <<training_baseline.criticality[p]<<','<<(eval.misses.count(p)?eval.misses.at(p):0)<<'\n';
        summary<<"capacity_pages,selected_pages,placement_overlap,all_slow_ns,frequency_ns,criticality_ns,reduction_percent\n";
        std::cout<<std::fixed<<std::setprecision(3)<<"Trace: "<<path<<"\nCriticality metric: "<<criticality
            <<"\nTraining eligible pages: "<<ranking.misses.size()
            <<"; evaluation miss pages: "<<eval.misses.size()<<"\ncapacity\tfrequency_ns\tcriticality_ns\treduction_percent\n";
        for(size_t capacity:capacities) {
            auto f=rank(ranking,training_baseline,capacity,false),k=rank(ranking,training_baseline,capacity,true);
            double ft=replay(eval,f,c).total,kt=replay(eval,k,c).total;
            size_t overlap=0;for(Page p:f) overlap+=k.count(p);
            double gain=100*(ft-kt)/ft;
            summary<<std::setprecision(17)<<capacity<<','<<f.size()<<','<<overlap<<','<<eval_baseline.total<<','<<ft<<','<<kt<<','<<gain<<'\n';
            std::cout<<capacity<<'\t'<<ft<<'\t'<<kt<<'\t'<<gain<<'\n';
            std::ofstream placements(prefix+"_placement_"+std::to_string(capacity)+".csv");
            if(!placements) throw std::runtime_error("Cannot write placements");
            placements<<"page,frequency_selected,criticality_selected\n";
            Placement all=f;all.insert(k.begin(),k.end());
            for(Page p:all) placements<<p<<','<<f.count(p)<<','<<k.count(p)<<'\n';
        }
        return 0;
    }catch(const std::exception& e){std::cerr<<"Error: "<<e.what()<<'\n';return 1;}
}
