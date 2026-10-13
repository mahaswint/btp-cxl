#define main trace_profiler_cli_main
#include "trace_profiler.cpp"
#undef main
#include <sstream>

void check(bool pass,const char* message) {
    if(!pass) throw std::runtime_error(message);
}
void near(double a,double b) { check(std::abs(a-b)<1e-7,"Unexpected modeled time"); }
int main() {
    Config c;c.core_ns=1;c.fast_ns=10;c.slow_ns=100;c.width=100;c.rob=100;c.mlp=100;
    Segment serial;
    serial.nodes={{{},{1},0,{}},{{0},{2},0,{}}};
    serial.misses={{1,1},{2,1}};
    near(replay(serial,{},c).total,202);
    near(replay(serial,{1},c).total,112);
    near(replay(serial,{1,2},c).total,22);
    auto serial_profile=replay(serial,{},c,true);
    near(serial_profile.total,replay(serial,{},c).total);
    near(serial_profile.criticality.at(1),90);
    near(serial_profile.criticality.at(2),90);

    Segment parallel;parallel.nodes={{{},{1},0,{}},{{},{2},0,{}}};
    near(replay(parallel,{},c).total,101);
    near(replay(parallel,{1},c).total,101);
    c.mlp=1;near(replay(parallel,{},c).total,202);
    c.mlp=100;c.rob=1;near(replay(parallel,{},c).total,202);
    c.rob=100;c.width=1;near(replay(parallel,{},c).total,102);
    near(replay(parallel,{},c,true).total,replay(parallel,{},c).total);

    c.width=100;
    Segment masked;
    masked.nodes={{{},{1,1,1,1,1,1,1,1,1,1},0,{}},{{},{},1000,{}},{{1},{2},0,{}}};
    masked.misses={{1,10},{2,1}};
    c.hit_ns=4;
    auto profile=replay(masked,{},c,true);
    near(profile.criticality.at(1),0);near(profile.criticality.at(2),90);
    check(rank(masked,profile,1,false)==Placement{1},"Frequency ranking failed");
    check(rank(masked,profile,1,true)==Placement{2},"Criticality ranking failed");
    check(replay(masked,{2},c).total<replay(masked,{1},c).total,"Masked case must favor criticality");

    c.cache_kib=1;c.ways=1;Cache cache(c);
    check(cache.miss(64),"Cold access must miss");
    check(!cache.miss(64),"Repeated access must hit");
    check(cache.miss(64+1024),"Conflicting line must miss");
    check(cache.miss(64),"Evicted line must miss");
    std::string bytes(64,'\0');bytes[10]=7;bytes[12]=3;bytes[32]=64;
    std::istringstream in(bytes);
    auto decoded=read(in);
    check(decoded.dst[0]==7 && decoded.src[0]==3 && decoded.loads[0]==64,"Trace decode failed");
    std::string consumer(64,'\0');consumer[12]=7;consumer[32]=64;
    std::istringstream chained(bytes+consumer);
    Cache fresh(c);
    auto loaded=load(chained,2,fresh,true);
    check(loaded.nodes[1].deps==std::vector<int>{0},"Register producer edge missing");
    check(loaded.nodes[0].misses.size()==1 && loaded.nodes[1].hits==1,"Trace cache filtering failed");
    bool rejected=false;std::istringstream truncated(bytes.substr(0,63));
    try {read(truncated);}catch(const std::exception&){rejected=true;}
    check(rejected,"Truncated record accepted");
    // PACT-style T1/T2: parallel requests increase average active occupancy.
    c.pac_window_ns=1000;c.pac_alpha=1;c.pac_k_dram_ns=10;c.pac_k_cxl_ns=100;
    Timing requests;requests.total=300;
    requests.requests={{0,100,1,false},{0,100,2,false},{200,210,3,true}};
    auto pac=pac_profile(requests,c);
    near(pac.scores.criticality.at(1),50);near(pac.scores.criticality.at(2),50);
    near(pac.scores.criticality.at(3),10);
    for(const auto& window:pac.windows) near(window.stalls_ns,window.attributed_ns);
    check(pac.windows.size()==2,"Expected separate DRAM/CXL counters");
    near(pac.windows[0].mlp,2);near(pac.windows[1].mlp,1);

    // In one window/tier, page attribution is proportional to miss frequency.
    Timing one_window;one_window.total=300;
    one_window.requests={{0,100,1,false},{100,200,1,false},{200,300,2,false}};
    auto one=pac_profile(one_window,c);
    near(one.scores.criticality.at(1),2*one.scores.criticality.at(2));

    // Cross-window occupancy is clipped, with each request counted once.
    c.pac_window_ns=100;
    Timing crossing;crossing.total=150;crossing.requests={{50,150,1,false}};
    auto cross=pac_profile(crossing,c);
    check(cross.windows.size()==2,"Cross-boundary request lost");
    near(cross.windows[0].occupancy_ns,50);near(cross.windows[1].occupancy_ns,50);
    check(cross.windows[0].misses==1 && cross.windows[1].misses==0,"Miss double counted");
    near(cross.scores.criticality.at(1),100);

    // Serial versus overlapping phases produce distinct per-window weights.
    Timing phases;phases.total=200;
    phases.requests={{0,100,1,false},{100,200,2,false},{100,200,3,false}};
    auto phase=pac_profile(phases,c);
    near(phase.scores.criticality.at(1),100);near(phase.scores.criticality.at(2),50);
    c.pac_alpha=.5;
    auto cooled=pac_profile(phases,c);near(cooled.scores.criticality.at(1),50);
    near(cooled.scores.criticality.at(2),50);
    c.pac_alpha=0;
    auto reset=pac_profile(phases,c);near(reset.scores.criticality.at(1),0);
    near(reset.scores.criticality.at(2),50);

    // Only demand-load misses enter the PEBS-equivalent attribution stream.
    Segment stores;Node store;store.misses={1};store.miss_loads={false};
    stores.nodes.push_back(store);
    check(replay(stores,{},c,false,true).requests.empty(),"Store sampled as demand load");
    std::cout<<"Timing/cache/trace and PAC occupancy, attribution, windows, cooling and load-domain checks passed.\n";
}
