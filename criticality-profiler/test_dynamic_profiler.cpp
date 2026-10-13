#define main static_profiler_main
#include "trace_profiler.cpp"
#undef main
#include "dynamic_model.h"

void require(bool pass,const char* message) {if(!pass) throw std::runtime_error(message);}
void close(double a,double b) {require(std::abs(a-b)<1e-7,"Unexpected runtime value");}
int main() {
    Config c;c.core_ns=1;c.hit_ns=1;c.fast_ns=10;c.slow_ns=100;
    c.width=100;c.rob=100;c.mlp=2;c.pac_window_ns=10000;
    RuntimeConfig rc;rc.capacity=1;rc.batch=1;rc.copy_gbps=4096;rc.move_overhead_ns=2;
    Segment serial;serial.nodes={{{},{1},0,{}},{{0},{2},0,{}}};
    close(dynamic_replay(serial,c,rc,"cxl").runtime_ns,202);
    close(dynamic_replay(serial,c,rc,"dram").runtime_ns,22);
    auto f=dynamic_replay(serial,c,rc,"frequency"),p=dynamic_replay(serial,c,rc,"pac");
    close(f.runtime_ns,112);close(p.runtime_ns,f.runtime_ns);
    require(p.decisions.empty(),"Short trace must not receive future-based migrations");
    Segment parallel;parallel.nodes={{{},{1},0,{}},{{},{2},0,{}}};
    close(dynamic_replay(parallel,c,rc,"cxl").runtime_ns,101);
    c.mlp=1;close(dynamic_replay(parallel,c,rc,"cxl").runtime_ns,202);c.mlp=2;
    c.rob=1;close(dynamic_replay(parallel,c,rc,"cxl").runtime_ns,202);c.rob=100;

    Segment phase;phase.nodes={{{},{1},0,{}},{{0},{2},0,{}},{{1},{2},0,{}},{{2},{2},0,{}}};
    c.pac_window_ns=50;
    auto moved=dynamic_replay(phase,c,rc,"pac");
    close(moved.runtime_ns,140);close(moved.migration_ns,6);
    require(moved.promotions==1 && moved.demotions==1,"Expected one swap");
    require(moved.decisions.size()==1,"Do not migrate after completion");
    require(moved.decisions[0].plan.moves[0].page==1 && !moved.decisions[0].plan.moves[0].promotion,"Cold page must demote first");
    require(moved.final_dram==Placement{2},"Wrong final tier");
    close(moved.decisions[0].sample_ns,112);close(moved.decisions[0].resume_ns,118);
    Segment continuing=phase;
    for(int i=4;i<24;++i) continuing.nodes.push_back({{i-1},{2},0,{}});
    auto repeated=dynamic_replay(continuing,c,rc,"pac");
    require(repeated.decisions.size()>=3,"PAC must update continuously");
    for(size_t i=1;i<repeated.decisions.size();++i)
        require(repeated.decisions[i].sample_ns>repeated.decisions[i-1].resume_ns,"Sampling time regressed");
    rc.move_overhead_ns=10000;
    auto expensive=dynamic_replay(phase,c,rc,"pac");
    close(expensive.runtime_ns,20136);close(expensive.migration_ns,20002);
    require(expensive.runtime_ns>moved.runtime_ns,"Migration cost not charged");
    rc.move_overhead_ns=2;rc.capacity=0;
    auto zero=dynamic_replay(phase,c,rc,"pac");
    close(zero.runtime_ns,dynamic_replay(phase,c,rc,"cxl").runtime_ns);
    require(!zero.promotions && !zero.demotions && zero.decisions.empty(),"Zero capacity must not move pages");
    rc.capacity=1;rc.batch=0;
    auto disabled=dynamic_replay(phase,c,rc,"pac");close(disabled.runtime_ns,314);
    require(disabled.decisions.empty(),"Disabled migration must preserve static first touch");

    // Sampling must not attribute future requests or future occupancy.
    std::vector<Request> intervals{{0,100,1,false},{60,160,2,false},{0,10,3,true}};
    auto stats=observe(intervals,0,50,c);
    require(stats[0].misses==1 && stats[0].pages.count(2)==0,"Future page leaked into PAC");
    close(stats[0].area,50);close(stats[0].active,50);close(stats[0].mlp,1);
    close(stats[1].mlp,1);

    // Eager headroom creation demotes the least recently observed pages.
    rc.capacity=2;rc.batch=1;rc.reserve=1;
    RuntimePolicy policy(rc);policy.touch(1);policy.touch(2);policy.touch(1);
    TierStats slow;slow.misses=1;slow.stalls=100;slow.pages={{3,1}};
    policy.update(slow,c,true);
    auto plan=policy.decide();
    require(plan.moves.size()==3 && plan.moves[0].page==2,"LRU eager demotion failed");
    require(policy.dram==Placement{3},"Reserve headroom not maintained");
    policy.touch(4);
    require(policy.dram==Placement{3},"New pages must not refill eager reserve after initial fill");
    require(plan.bin_width>0 && plan.candidates==1,"Adaptive-bin fallback failed");

    RuntimePolicy a(rc),b(rc);
    for(Page page=1;page<=150;++page) {a.scores[page]=double(page*page);b.scores[page]=double(page*page);}
    auto pa=a.decide(),pb=b.decide();
    require(a.dram==b.dram && pa.bin_width==pb.bin_width,"Reservoir seed must be reproducible");
    require(a.dram.size()<=rc.capacity,"Capacity invariant broken");
    std::cout<<"Runtime dependency/MLP, causal sampling, adaptive bins, LRU reserve, migration cost and controls passed.\n";
}
