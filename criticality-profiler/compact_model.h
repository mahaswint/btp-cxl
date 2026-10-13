#pragma once
#include <cstring>
#include <unordered_set>
#include <functional>
// Versioned x86 little-endian IEEE-754 cache. CPU issue timing is analytical.
struct CompactEdge {uint32_t parent=0,reserved=0;double delay=0;};
struct CompactEvent {
    uint64_t instruction=0;double release=0;uint64_t edge_begin=0;
    uint32_t page=0,edges=0;uint8_t load=0,reserved[7]{};
};
static_assert(sizeof(CompactEvent)==40 && sizeof(CompactEdge)==16,"Compact format layout");
struct CompactGraph {
    uint64_t instructions=0,warmup=0,max_frontier=0;
    Config config;
    double tail_floor=0;
    std::vector<Page> pages;
    std::vector<CompactEvent> events;
    std::vector<CompactEdge> edges;
    std::vector<double> tail_delay;
};
struct ReadyExpr {
    double floor=0;
    std::vector<CompactEdge> terms;
    void reset(double f) {floor=f;terms.clear();}
    void merge(const ReadyExpr& other,const std::function<double(uint32_t,uint32_t)>& bound) {
        floor=std::max(floor,other.floor);
        for(const auto& t:other.terms) {
            auto p=std::find_if(terms.begin(),terms.end(),[&](const auto& a){return a.parent==t.parent;});
            if(p!=terms.end()){p->delay=std::max(p->delay,t.delay);continue;}
            bool redundant=false;
            for(size_t i=0;i<terms.size();) {
                const auto old=terms[i];
                if(old.parent<t.parent && bound(old.parent,t.parent)+t.delay>=old.delay) {
                    terms[i]=terms.back();terms.pop_back();continue;
                }
                if(t.parent<old.parent && bound(t.parent,old.parent)+old.delay>=t.delay){redundant=true;break;}
                ++i;
            }
            if(!redundant)terms.push_back(t);
        }
    }
    void assign(const ReadyExpr& other) {floor=other.floor;terms.assign(other.terms.begin(),other.terms.end());}
};
// One buffered raw pass. Miss provenance is retained within conservative epochs.
CompactGraph compile_compact(std::istream& in,uint64_t count,const Config& c) {
    CompactGraph g;g.config=c;g.instructions=count;g.warmup=c.warmup;
    Cache cache(c);
    std::array<ReadyExpr,256> registers;
    ReadyExpr ready;
    std::function<double(uint32_t,uint32_t)> bound;
    bound=[&](uint32_t a,uint32_t b)->double {
        if(a==b)return 0;
        if(a>b)return -std::numeric_limits<double>::infinity();
        const auto& e=g.events[b];double best=-std::numeric_limits<double>::infinity();
        for(size_t j=0;j<e.edges;++j) {
            const auto& edge=g.edges[e.edge_begin+j];
            if(edge.parent==a)best=std::max(best,edge.delay+std::min(c.fast_ns,c.slow_ns));
        }
        return best;
    };
    struct History {uint64_t read_i=UINT64_MAX,store_i=UINT64_MAX;ReadyExpr access,store;};
    std::unordered_map<uint64_t,History> history;
    std::vector<std::vector<uint64_t>> retired_lines(c.rob);
    std::unordered_map<Page,uint32_t> page_ids;
    std::vector<unsigned char> buffer(64*65536);
    uint64_t available=0,cursor=0;
    double compute_clock=0;
    uint32_t epoch_fence=UINT32_MAX;
    size_t epoch_first=0;
    auto close_epoch=[&](uint64_t instruction) {
        if(g.events.size()>epoch_first) {
            CompactEvent fence;fence.instruction=instruction;fence.release=compute_clock;fence.load=2;
            fence.edge_begin=g.edges.size();fence.edges=uint32_t(g.events.size()-epoch_first);
            for(size_t j=epoch_first;j<g.events.size();++j)
                g.edges.push_back({uint32_t(j),0,std::max(0.0,compute_clock-g.events[j].release)});
            epoch_fence=uint32_t(g.events.size());g.events.push_back(fence);g.tail_delay.push_back(0);
        }
        epoch_first=g.events.size();
        for(auto& r:registers)r.reset(0);
        history.clear();
    };
    auto next=[&](){
        if(cursor==available) {
            in.read(reinterpret_cast<char*>(buffer.data()),std::streamsize(buffer.size()));
            available=uint64_t(in.gcount());cursor=0;
            if(!available || available%64) throw std::runtime_error("Truncated raw trace");
        }
        const auto* b=buffer.data()+cursor;cursor+=64;
        if(b[8]>1 || b[9]>1) throw std::runtime_error("Invalid ChampSim branch fields");
        Instruction x;std::copy(b+10,b+12,x.dst.begin());std::copy(b+12,b+16,x.src.begin());
        for(int j=0;j<2;++j)x.stores[j]=u64(b+16+8*j);
        for(int j=0;j<4;++j)x.loads[j]=u64(b+32+8*j);
        return x;
    };
    for(uint64_t i=0;i<c.warmup;++i) {
        auto x=next();for(auto a:x.loads)if(a)cache.miss(a);for(auto a:x.stores)if(a)cache.miss(a);
    }
    for(uint64_t i=0;i<count;++i) {
        auto& expired=retired_lines[i%c.rob];
        for(uint64_t line:expired) {
            auto p=history.find(line);
            if(p!=history.end()) {
                if(p->second.read_i+c.rob<=i)p->second.access.reset(0);
                if(p->second.store_i!=UINT64_MAX && p->second.store_i+c.rob<=i)p->second.store.reset(0);
                if(p->second.read_i+c.rob<=i && (p->second.store_i==UINT64_MAX || p->second.store_i+c.rob<=i))history.erase(p);
            }
        }
        expired.clear();
        if(i && i%c.rob==0)close_epoch(i-1);
        auto x=next();ready.reset(compute_clock);
        if(epoch_fence!=UINT32_MAX)ready.terms.push_back({epoch_fence,0,0});
        for(auto r:x.src)if(r)ready.merge(registers[r],bound);
        std::array<uint32_t,6> misses{};std::array<bool,6> loads{};
        size_t nm=0,hits=0;
        std::array<std::pair<uint64_t,bool>,6> touched{};size_t nt=0;
        auto access=[&](uint64_t address,bool store) {
            if(!address)return;
            Page page=address/4096;uint64_t line=address/64;
            auto p=page_ids.find(page);
            if(p==page_ids.end()) {
                if(g.pages.size()>=UINT32_MAX)throw std::runtime_error("Too many pages");
                p=page_ids.emplace(page,uint32_t(g.pages.size())).first;g.pages.push_back(page);
            }
            if(cache.miss(address)){misses[nm]=p->second;loads[nm++]=!store;}else ++hits;
            auto h=history.find(line);
            if(h!=history.end()) {
                ready.merge(h->second.store,bound);
                if(store)ready.merge(h->second.access,bound);
            }
            touched[nt++]={line,store};
        };
        for(auto a:x.loads)access(a,false);
        for(auto a:x.stores)access(a,true);
        // Coarse compute work is aggregated on one analytical issue clock.
        // Register provenance carries miss ancestors, not every arithmetic op.
        compute_clock+=(c.core_ns+hits*c.hit_ns)/c.width;
        ready.floor=compute_clock;
        g.max_frontier=std::max(g.max_frontier,uint64_t(ready.terms.size()));
        if(ready.terms.size()>65536)throw std::runtime_error("Dependency frontier too large; no edges silently dropped");
        for(size_t j=0;j<nm;++j) {
            if(g.events.size()>=UINT32_MAX)throw std::runtime_error("Too many compact events");
            CompactEvent event;event.instruction=i;event.release=ready.floor;
            event.page=misses[j];event.load=loads[j];event.edge_begin=g.edges.size();event.edges=uint32_t(ready.terms.size());
            for(auto term:ready.terms) {
                term.delay=std::max(0.0,compute_clock-g.events[term.parent].release);
                g.edges.push_back(term);
            }
            uint32_t id=uint32_t(g.events.size());g.events.push_back(event);g.tail_delay.push_back(0);
            ready.reset(0);ready.terms.push_back({id,0,0});
        }
        g.tail_floor=std::max(g.tail_floor,ready.floor);
        for(const auto& t:ready.terms)g.tail_delay[t.parent]=std::max(g.tail_delay[t.parent],compute_clock-g.events[t.parent].release);
        for(auto r:x.dst)if(r)registers[r].assign(ready);
        for(size_t j=0;j<nt;++j) {
            auto& h=history[touched[j].first];h.read_i=i;h.access.assign(ready);
            if(touched[j].second){h.store_i=i;h.store.assign(ready);}
            expired.push_back(touched[j].first);
        }
    }
    close_epoch(count?count-1:0);
    return g;
}
template<class T> void compact_write(std::ostream& out,const T& v) {out.write(reinterpret_cast<const char*>(&v),sizeof(v));}
template<class T> void compact_read(std::istream& in,T& v) {if(!in.read(reinterpret_cast<char*>(&v),sizeof(v)))throw std::runtime_error("Truncated compact cache");}
template<class T> void compact_write_vector(std::ostream& out,const std::vector<T>& v) {
    uint64_t n=v.size();compact_write(out,n);out.write(reinterpret_cast<const char*>(v.data()),std::streamsize(n*sizeof(T)));
}
template<class T> void compact_read_vector(std::istream& in,std::vector<T>& v) {
    uint64_t n;compact_read(in,n);
    auto here=in.tellg();in.seekg(0,std::ios::end);auto remaining=in.tellg()-here;in.seekg(here);
    if(n>uint64_t(remaining)/sizeof(T))throw std::runtime_error("Invalid compact vector length");
    v.resize(size_t(n));if(n && !in.read(reinterpret_cast<char*>(v.data()),std::streamsize(n*sizeof(T))))throw std::runtime_error("Truncated compact data");
}
void save_compact(const CompactGraph& g,const std::string& path) {
    std::ofstream out(path,std::ios::binary);uint64_t magic=0x3254434150434343ULL;compact_write(out,magic);
    compact_write(out,g.instructions);compact_write(out,g.warmup);compact_write(out,g.max_frontier);
    compact_write(out,g.config.cache_kib);compact_write(out,g.config.ways);compact_write(out,g.config.width);compact_write(out,g.config.rob);
    compact_write(out,g.config.core_ns);compact_write(out,g.config.hit_ns);compact_write(out,g.config.fast_ns);compact_write(out,g.config.slow_ns);compact_write(out,g.tail_floor);
    compact_write_vector(out,g.pages);compact_write_vector(out,g.events);compact_write_vector(out,g.edges);compact_write_vector(out,g.tail_delay);
    if(!out)throw std::runtime_error("Cannot write compact cache");
}
CompactGraph load_compact(const std::string& path) {
    std::ifstream in(path,std::ios::binary);CompactGraph g;uint64_t magic;compact_read(in,magic);
    if(magic!=0x3254434150434343ULL)throw std::runtime_error("Unknown compact cache version");
    compact_read(in,g.instructions);compact_read(in,g.warmup);compact_read(in,g.max_frontier);
    compact_read(in,g.config.cache_kib);compact_read(in,g.config.ways);compact_read(in,g.config.width);compact_read(in,g.config.rob);
    compact_read(in,g.config.core_ns);compact_read(in,g.config.hit_ns);compact_read(in,g.config.fast_ns);compact_read(in,g.config.slow_ns);compact_read(in,g.tail_floor);
    compact_read_vector(in,g.pages);compact_read_vector(in,g.events);compact_read_vector(in,g.edges);compact_read_vector(in,g.tail_delay);
    if(g.events.size()!=g.tail_delay.size())throw std::runtime_error("Invalid compact tail size");
    for(double delay:g.tail_delay)if(!std::isfinite(delay) || delay<0)throw std::runtime_error("Invalid compute tail");
    for(size_t i=0;i<g.events.size();++i) {
        const auto& e=g.events[i];
        if(e.page>=g.pages.size() || e.load>2 || e.edge_begin>g.edges.size() || e.edges>g.edges.size()-e.edge_begin || !std::isfinite(e.release) || e.release<0)
            throw std::runtime_error("Invalid compact event");
        for(size_t j=0;j<e.edges;++j) {
            const auto& edge=g.edges[e.edge_begin+j];
            if(edge.parent>=i || !std::isfinite(edge.delay) || edge.delay<0)throw std::runtime_error("Invalid compact dependency");
        }
    }
    return g;
}
// Only memory requests are scheduled. Arithmetic/cache-hit chains live on edges.
DynamicResult replay_compact(const CompactGraph& g,const Config& c,const RuntimeConfig& rc,const std::string& mode) {
    if(std::min(c.fast_ns,c.slow_ns)<std::min(g.config.fast_ns,g.config.slow_ns))
        throw std::runtime_error("Rebuild compact graph for a lower service-latency bound");
    const bool managed=mode=="frequency" || mode=="pac";
    if(!managed && mode!="dram" && mode!="cxl")throw std::runtime_error("Unknown policy");
    RuntimePolicy policy(rc);DynamicResult result;
    const size_t n=g.events.size();
    std::vector<uint32_t> remaining(n);std::vector<double> ready_time(n),finish(n);
    std::vector<size_t> offsets(n+1,0);
    for(const auto& e:g.edges)++offsets[e.parent+1];
    for(size_t i=1;i<offsets.size();++i)offsets[i]+=offsets[i-1];
    struct Child {uint32_t id;double delay;};std::vector<Child> children(g.edges.size());
    auto cursor=offsets;
    using Item=std::pair<double,uint32_t>;
    std::priority_queue<Item,std::vector<Item>,std::greater<Item>> ready,active;
    std::vector<bool> dram(n);
    for(size_t i=0;i<n;++i) {
        const auto& e=g.events[i];remaining[i]=e.edges;ready_time[i]=e.release;
        if(!e.edges)ready.push({e.release,uint32_t(i)});
        for(size_t j=0;j<e.edges;++j) {const auto& d=g.edges[e.edge_begin+j];children[cursor[d.parent]++]={uint32_t(i),d.delay};}
    }
    std::array<TierStats,2> stats;
    size_t outstanding[2]={0,0},completed=0;
    uint64_t slow_counter=0;
    double now=0,next_sample=c.pac_window_ns,drain_start=0;
    bool draining=false;
    bool periodic=managed && rc.capacity && (rc.batch || rc.reserve);
    size_t memory_total=0,memory_completed=0;
    for(const auto& e:g.events)memory_total+=e.load<2;
    auto advance=[&](double time) {
        for(size_t tier=0;tier<2;++tier)if(outstanding[tier]) {
            stats[tier].area+=outstanding[tier]*(time-now);stats[tier].active+=time-now;
        }
        now=time;
    };
    while(completed<n) {
        while(!active.empty() && active.top().first<=now) {
            auto [end,id]=active.top();active.pop();finish[id]=end;++completed;
            memory_completed+=g.events[id].load<2;
            if(g.events[id].load==1)--outstanding[dram[id]?1:0];
            for(size_t j=offsets[id];j<offsets[id+1];++j) {
                auto child=children[j];ready_time[child.id]=std::max(ready_time[child.id],end+child.delay);
                if(--remaining[child.id]==0)ready.push({ready_time[child.id],child.id});
            }
        }
        if(completed==n)break;
        if(memory_completed==memory_total){periodic=false;draining=false;}
        if(periodic && !draining && now>=next_sample){draining=true;drain_start=now;}
        if(draining && active.empty()) {
            Decision d;d.sample_ns=now+result.migration_ns+result.sampling_ns;d.drain_ns=now-drain_start;
            for(size_t tier=0;tier<2;++tier)if(stats[tier].active>0) {
                stats[tier].mlp=stats[tier].area/stats[tier].active;
                double k=tier?(c.pac_k_dram_ns>0?c.pac_k_dram_ns:c.fast_ns):(c.pac_k_cxl_ns>0?c.pac_k_cxl_ns:c.slow_ns);
                stats[tier].stalls=k*stats[tier].misses/stats[tier].mlp;
            }
            d.tiers=std::move(stats);stats={};policy.update(d.tiers[0],c,mode=="pac");d.plan=policy.decide();
            for(const auto& move:d.plan.moves) {
                if(move.promotion)++result.promotions;else ++result.demotions;
                d.move_ns+=rc.move_overhead_ns+4096/rc.copy_gbps;
            }
            result.migration_ns+=d.move_ns;result.sampling_ns+=rc.sampling_cost_ns;result.drain_ns+=d.drain_ns;
            d.resume_ns=d.sample_ns+d.move_ns+rc.sampling_cost_ns;d.resident=policy.dram.size();
            result.decisions.push_back(std::move(d));next_sample=now+c.pac_window_ns;draining=false;
        }
        if(!draining)while(!ready.empty() && ready.top().first<=now && active.size()<c.mlp) {
            uint32_t id=ready.top().second;ready.pop();const auto& e=g.events[id];Page page=g.pages[e.page];
            if(e.load==2){active.push({now,id});continue;}
            if(managed)policy.touch(page);
            bool fast=mode=="dram" || (managed && policy.dram.count(page));dram[id]=fast;
            if(e.load==1) {
                size_t tier=fast?1:0;++outstanding[tier];++stats[tier].misses;
                bool sampled=fast || (++slow_counter%rc.pebs_period==0);
                if(sampled) {
                    ++stats[tier].pages[page];
                    if(rc.bin_count && !fast)stats[tier].sample_order.push_back(page);
                }
                if(fast)++result.dram_loads;else ++result.cxl_loads;
            }
            active.push({now+(fast?c.fast_ns:c.slow_ns),id});
        }
        double event=std::numeric_limits<double>::infinity();
        if(!active.empty())event=active.top().first;
        if(!draining) {
            if(!ready.empty() && active.size()<c.mlp)event=std::min(event,ready.top().first);
            if(periodic)event=std::min(event,next_sample);
        }
        if(event==now && !active.empty())continue;
        if(!std::isfinite(event) || event<now)throw std::runtime_error("Compact scheduler stalled");
        advance(event);
    }
    double total=std::max(now,g.tail_floor);
    for(size_t i=0;i<n;++i)total=std::max(total,finish[i]+g.tail_delay[i]);
    result.runtime_ns=total+result.migration_ns+result.sampling_ns;result.final_dram=policy.dram;
    return result;
}
