#define main static_profiler_main
#include "trace_profiler.cpp"
#undef main
#include "dynamic_model.h"
#include "compact_model.h"
#include <sstream>
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
void near(double a,double b){require(std::abs(a-b)<1e-7,"Wrong analytical time");}
std::string trace_bytes(size_t n,bool serial) {
    std::string bytes;
    for(size_t i=0;i<n;++i) {
        std::array<unsigned char,64> b{};
        if(serial){b[10]=1;b[12]=1;}
        uint64_t address=(i+1)*4096;
        for(size_t j=0;j<8;++j)b[32+j]=uint8_t(address>>(8*j));
        bytes.append(reinterpret_cast<const char*>(b.data()),64);
    }
    return bytes;
}
int main() {
    Config c;c.warmup=0;c.core_ns=1;c.hit_ns=2;c.fast_ns=10;c.slow_ns=100;c.pac_window_ns=10000;c.mlp=2;c.width=1;
    RuntimeConfig rc;rc.capacity=0;
    std::istringstream pure(std::string(64*100,'\0'));auto pure_graph=compile_compact(pure,100,c);
    require(pure_graph.events.empty(),"Compute-only instructions should not create memory events");
    near(replay_compact(pure_graph,c,rc,"cxl").runtime_ns,100);
    std::istringstream serial(trace_bytes(3,true));auto sg=compile_compact(serial,3,c);
    near(replay_compact(sg,c,rc,"cxl").runtime_ns,303);
    near(replay_compact(sg,c,rc,"dram").runtime_ns,33);
    require(sg.events.size()==4 && sg.edges.size()==5,"Serial dependency contraction failed");
    c.width=4;std::istringstream parallel(trace_bytes(4,false));auto pg=compile_compact(parallel,4,c);
    near(replay_compact(pg,c,rc,"cxl").runtime_ns,200.5);
    // Cache filtering and accessed-page accounting must match the original reader.
    std::string raw=trace_bytes(128,true);raw+=raw;
    Config check=c;check.cache_kib=4;check.ways=1;check.warmup=16;
    std::istringstream baseline(raw);Cache cache(check);load(baseline,16,cache,false);
    auto segment=load(baseline,240,cache,true);
    std::istringstream input(raw);auto graph=compile_compact(input,240,check);
    size_t misses=0,loads=0;for(const auto& n:segment.nodes){misses+=n.misses.size();for(bool load:n.miss_loads)loads+=load;}
    size_t actual_misses=0;for(const auto& e:graph.events)actual_misses+=e.load!=2;
    require(actual_misses==misses && graph.pages.size()==segment.accesses.size(),"Cache or footprint mismatch");
    auto result=replay_compact(graph,check,rc,"cxl");require(result.cxl_loads==loads,"Load conservation failed");
    // Equal frequencies in distinct overlap windows: PAC must retain the weighting.
    RuntimeConfig policy_config;policy_config.capacity=1;policy_config.batch=1;
    RuntimePolicy frequency(policy_config),pac(policy_config);
    frequency.touch(99);pac.touch(99);
    TierStats low;low.misses=2;low.mlp=1;low.stalls=200;low.pages={{2,2}};
    TierStats high;high.misses=2;high.mlp=2;high.stalls=100;high.pages={{1,2}};
    frequency.update(low,c,false);frequency.update(high,c,false);
    pac.update(low,c,true);pac.update(high,c,true);
    frequency.decide();pac.decide();
    require(frequency.dram==Placement{1} && pac.dram==Placement{2},"MLP-weighted page selection failed");
    RuntimePolicy serial_f(policy_config),serial_p(policy_config);
    serial_f.touch(99);serial_p.touch(99);high.mlp=1;high.stalls=200;
    serial_f.update(low,c,false);serial_f.update(high,c,false);
    serial_p.update(low,c,true);serial_p.update(high,c,true);
    serial_f.decide();serial_p.decide();require(serial_f.dram==serial_p.dram,"Constant MLP control should tie");
    // A bounded highest bin must admit several high scores even with one huge outlier.
    RuntimeConfig bins;bins.capacity=20;bins.batch=20;bins.bin_count=20;bins.bin_scale_threshold=.7;
    RuntimePolicy bounded(bins);
    for(Page page=1;page<=100;++page)bounded.scores[page]=double(page);
    bounded.scores[101]=10000;bounded.scores[102]=20000;bounded.scores[103]=1e9;
    auto bin_plan=bounded.decide();require(bin_plan.candidates>=3,"High scores must saturate the final bin");
    require(bounded.dram.count(101) && bounded.dram.count(102) && bounded.dram.count(103),"Bounded bin lost eligible pages");
    // Sample attribution uses true aggregate stalls and sampled counts separately.
    RuntimePolicy sampled(bins);TierStats sparse;sparse.misses=800;sparse.stalls=80000;sparse.pages={{1,1},{2,1}};
    sparse.sample_order={1,2};sampled.update(sparse,c,true);
    near(sampled.scores[1],40000);near(sampled.scores[2],40000);
    require(sampled.reservoir_seen==2 && sampled.access_reservoir.size()==2,"Access reservoir failed");
    // PAC decay applies before new attribution, including request-free windows.
    bins.pac_decay=.7;RuntimePolicy decayed(bins),undecayed_frequency(bins);
    decayed.update(sparse,c,true);undecayed_frequency.update(sparse,c,false);
    TierStats idle;decayed.update(idle,c,true);undecayed_frequency.update(idle,c,false);
    near(decayed.scores[1],28000);near(decayed.access_reservoir[0],28000);
    near(undecayed_frequency.scores[1],1);
    decayed.update(sparse,c,true);near(decayed.scores[1],59600);
    // Retained DRAM history must cool too; changing the decay must not change tier residency.
    decayed.touch(1);auto resident=decayed.dram;
    decayed.update(idle,c,true);near(decayed.scores[1],41720);require(decayed.dram==resident,"Decay changed placement without a decision");
    bins.pac_decay=-1;
    RuntimeConfig matched_recency;matched_recency.capacity=1;matched_recency.batch=1;
    matched_recency.pac_decay=.7;matched_recency.frequency_decay=.7;
    RuntimePolicy recent_f(matched_recency),recent_p(matched_recency);
    recent_f.touch(99);recent_p.touch(99);
    for(size_t window=0;window<4;++window) {
        TierStats same_cost;same_cost.misses=2;same_cost.stalls=200;same_cost.pages={{1+window%2,2}};
        recent_f.update(same_cost,c,false);recent_p.update(same_cost,c,true);
        recent_f.decide();recent_p.decide();require(recent_f.dram==recent_p.dram,"Matched decay constant-MLP control diverged");
    }
    // Bounded/access-reservoir policy is invariant to constant score scaling.
    // It must not manufacture a criticality benefit with constant per-miss cost.
    RuntimePolicy bounded_f(bins),bounded_p(bins);
    for(Page page=1000;page<1020;++page){bounded_f.touch(page);bounded_p.touch(page);}
    for(size_t window=0;window<4;++window) {
        TierStats constant;constant.misses=400;constant.stalls=40000;
        for(size_t sample=0;sample<400;++sample){Page page=1+(sample+window)%40;
            bounded_f.touch(page);bounded_p.touch(page);
            ++constant.pages[page];constant.sample_order.push_back(page);}
        bounded_f.update(constant,c,false);bounded_p.update(constant,c,true);
        auto f=bounded_f.decide(),p=bounded_p.decide();
        require(bounded_f.dram==bounded_p.dram && f.moves.size()==p.moves.size(),"Bounded constant-cost control diverged");
    }
    // Runtime migrations: exact copy charges and total promotion cap.
    c.pac_window_ns=50;rc.capacity=1;rc.batch=1;rc.move_overhead_ns=2;rc.copy_gbps=4096;rc.promotion_budget=1;
    auto moved=replay_compact(sg,c,rc,"pac");
    require(moved.promotions==1 && moved.demotions==1,"Expected one charged swap");near(moved.migration_ns,6);
    for(const auto& d:moved.decisions)require(d.resident<=1 && d.resume_ns<=moved.runtime_ns,"Capacity or event timing broken");
    // Store-only traffic consumes latency/slots but must not enter demand-load PAC.
    for(auto& e:sg.events)if(e.load!=2)e.load=0;
    auto stores=replay_compact(sg,c,rc,"pac");require(!stores.cxl_loads && !stores.dram_loads && !stores.promotions,"Store attribution failed");
    std::cout<<"Compact contraction, cache/domain conservation, serial/parallel timing, PAC mechanism/control and migration budget passed.\n";
}
