// Designed LLC-miss streams: a controlled mechanism experiment, not a hardware trace.
#define DYNAMIC_PROFILER_LIBRARY
#include "dynamic_profiler.cpp"
#include <chrono>
#include <filesystem>

struct StreamPhase {
    std::string name;
    Page first;
    size_t pages,width;
    uint64_t loads;
};
struct StreamRun {
    DynamicResult result;
    size_t critical_resident=0,hot_resident=0;
};
void check(bool ok,const char* text){if(!ok)throw std::runtime_error(text);}

// Batches are dependency-separated: width=1 is a pointer chain; wider batches
// issue independent requests together and the next batch waits for completion.
// Full page cycles have identical costs until placement changes, so repetition
// is aggregated exactly instead of scheduling every individual request.
StreamRun simulate_stream(const std::vector<StreamPhase>& phases,const Config& c,
    const RuntimeConfig& rc,const std::string& mode,Page critical,Page hot,size_t pages) {
    const bool managed=mode=="frequency" || mode=="pac";
    RuntimePolicy policy(rc);StreamRun run;
    if(managed)for(Page p=1;p<=rc.capacity;++p)policy.touch(p); // identical cold warmup residency
    std::array<TierStats,2> stats;
    double execution=0,next_sample=c.pac_window_ns,last_sample=0;
    auto observe_window=[&] {
        Decision d;d.sample_ns=execution+run.result.migration_ns;
        d.drain_ns=std::max(0.0,execution-next_sample);
        for(size_t tier=0;tier<2;++tier)if(stats[tier].active>0) {
            stats[tier].mlp=stats[tier].area/stats[tier].active;
            double k=tier?c.fast_ns:c.slow_ns;
            stats[tier].stalls=k*stats[tier].misses/stats[tier].mlp;
        }
        d.tiers=std::move(stats);stats={};
        policy.update(d.tiers[0],c,mode=="pac");d.plan=policy.decide();
        for(const auto& m:d.plan.moves) {
            if(m.promotion)++run.result.promotions;else ++run.result.demotions;
            d.move_ns+=rc.move_overhead_ns+4096/rc.copy_gbps;
        }
        run.result.migration_ns+=d.move_ns;run.result.drain_ns+=d.drain_ns;
        d.resume_ns=d.sample_ns+d.move_ns;d.resident=policy.dram.size();
        run.result.decisions.push_back(std::move(d));last_sample=execution;
        next_sample=execution+c.pac_window_ns;
    };
    uint64_t total_loads=0;
    for(const auto& phase:phases)total_loads+=phase.loads;
    uint64_t processed=0;
    for(const auto& phase:phases) {
        check(phase.pages%phase.width==0,"Width must divide the page-cycle size");
        uint64_t left=phase.loads;size_t position=0;
        while(left) {
            if(managed && execution>=next_sample && processed<total_loads)observe_window();
            // Cost/stats of one cycle beginning at this position, or one batch
            // when a full cycle would cross the next observation boundary.
            auto block=[&](size_t count,uint64_t repeats,bool apply) {
                double time=0;std::array<TierStats,2> unit;
                std::vector<Page> slow_order,touch_order;
                for(size_t offset=0;offset<count;offset+=phase.width) {
                    size_t width=std::min(phase.width,count-offset),tier_count[2]={0,0};
                    for(size_t j=0;j<width;++j) {
                        Page page=phase.first+(position+offset+j)%phase.pages;
                        bool fast=mode=="dram" || (managed && policy.dram.count(page));
                        ++tier_count[fast?1:0];
                        if(managed) {++unit[fast?1:0].pages[page];touch_order.push_back(page);if(!fast)slow_order.push_back(page);}
                    }
                    time+=(tier_count[0]?c.slow_ns:c.fast_ns);
                    for(size_t tier=0;tier<2;++tier)if(tier_count[tier]) {
                        double latency=tier?c.fast_ns:c.slow_ns;
                        unit[tier].misses+=tier_count[tier];unit[tier].area+=tier_count[tier]*latency;
                        unit[tier].active+=latency;
                    }
                }
                if(!apply)return time;
                execution+=time*double(repeats);
                run.result.cxl_loads+=unit[0].misses*repeats;
                run.result.dram_loads+=unit[1].misses*repeats;
                if(managed) {
                    for(size_t tier=0;tier<2;++tier) {
                        stats[tier].misses+=unit[tier].misses*repeats;
                        stats[tier].area+=unit[tier].area*double(repeats);stats[tier].active+=unit[tier].active*double(repeats);
                        for(const auto& p:unit[tier].pages) {
                            stats[tier].pages[p.first]+=p.second*repeats;
                        }
                    }
                    // Only the final repetition determines relative LRU order.
                    for(Page page:touch_order)policy.touch(page);
                    // Preserve access order for the existing bounded policy's
                    // reservoir; a repeated full cycle ends on the same pages.
                    for(uint64_t r=0;r<repeats;++r)
                        stats[0].sample_order.insert(stats[0].sample_order.end(),slow_order.begin(),slow_order.end());
                }
                return time;
            };
            double cycle_time=block(phase.pages,1,false);
            uint64_t repeats=left/phase.pages;
            if(managed)repeats=std::min(repeats,uint64_t(std::max(0.0,std::floor((next_sample-execution)/cycle_time))));
            size_t count;
            if(repeats)count=phase.pages;
            else {repeats=1;count=size_t(std::min<uint64_t>(phase.width,left));}
            block(count,repeats,true);
            uint64_t done=uint64_t(count)*repeats;left-=done;processed+=done;
            position=(position+count)%phase.pages;
        }
    }
    check(processed==total_loads,"Stream request count changed");
    check(run.result.cxl_loads+run.result.dram_loads==total_loads,"Load conservation failed");
    check(last_sample<=execution,"Observation beyond execution end");
    run.result.runtime_ns=execution+run.result.migration_ns;run.result.final_dram=policy.dram;
    for(Page p:policy.dram){run.critical_resident+=p>=critical && p<critical+pages;run.hot_resident+=p>=hot && p<hot+pages;}
    check(policy.dram.size()<=rc.capacity,"Capacity exceeded");
    return run;
}

void analytical_checks() {
    Config c;c.fast_ns=90;c.slow_ns=190;c.pac_window_ns=20000000;
    RuntimeConfig rc;rc.capacity=0;
    auto serial=simulate_stream({{"serial",100,4,1,4}},c,rc,"cxl",100,200,4);
    auto parallel=simulate_stream({{"parallel",100,4,4,4}},c,rc,"cxl",100,200,4);
    auto cycles=simulate_stream({{"cycles",100,4,4,8}},c,rc,"cxl",100,200,4);
    auto partial=simulate_stream({{"partial",100,4,4,5}},c,rc,"cxl",100,200,4);
    check(serial.result.runtime_ns==760 && parallel.result.runtime_ns==190 &&
        cycles.result.runtime_ns==380 && partial.result.runtime_ns==380,"Analytical batch timing check failed");
    rc.capacity=2;
    auto mixed=simulate_stream({{"mixed",1,4,4,4}},c,rc,"frequency",1,100,4);
    check(mixed.result.runtime_ns==190 && mixed.result.dram_loads==2 && mixed.result.cxl_loads==2,
        "Mixed-tier parallel batch check failed");
    c.pac_alpha=.7;RuntimePolicy decay(rc);decay.scores[100]=100;
    TierStats observation;observation.misses=1;observation.stalls=50;observation.pages={{200,1}};
    decay.update(observation,c,true);
    check(std::abs(decay.scores[100]-70)<1e-9 && std::abs(decay.scores[200]-50)<1e-9,
        "PAC decay/contribution check failed");
    decay.update(TierStats{},c,true);
    check(std::abs(decay.scores[100]-49)<1e-9 && std::abs(decay.scores[200]-35)<1e-9,
        "Empty-window decay check failed");
}

int main(int argc,char** argv) {
    try {
        analytical_checks();
        std::string out="results/synthetic_streams",selected;size_t rounds=12;double alpha=1,window_ms=20;
        for(int i=1;i<argc;++i){check(i+1<argc,"Missing option value");std::string key=argv[i],value=argv[++i];
            if(key=="--out")out=value;else if(key=="--rounds")rounds=integer(value);
            else if(key=="--alpha"){alpha=nonnegative(value);check(alpha<=1,"Alpha must be in [0,1]");}
            else if(key=="--window-ms")window_ms=positive(value);
            else if(key=="--scenario")selected=value;else throw std::runtime_error("Unknown option");}
        if(!selected.empty())check(selected=="hot_first_mlp1" || selected=="hot_first_mlp2" ||
            selected=="hot_first_mlp4" || selected=="hot_first_mlp8" || selected=="hot_first_mlp16" ||
            selected=="critical_first_mlp16","Unknown scenario");
        check(rounds>=4 && rounds<=100,"Use 4 through 100 rounds");
        std::filesystem::create_directories(out);
        Config c;c.warmup=0;c.fast_ns=90;c.slow_ns=190;c.pac_window_ns=window_ms*1000000;c.pac_alpha=alpha;
        check(std::isfinite(c.pac_window_ns) && c.pac_window_ns>0,"Invalid observation window");
        RuntimeConfig rc;rc.capacity=1024;rc.batch=128;rc.bin_count=20;rc.bin_scale_threshold=.7;rc.promotion_budget=1024;
        const Page hot=100000,critical=200000;const size_t pages=1024;
        const uint64_t critical_loads=pages*412,hot_loads=critical_loads*4;
        std::ofstream results(out+"/summary.csv"),inputs(out+"/streams.csv"),report(out+"/REPORT.md");
        check(bool(results)&&bool(inputs)&&bool(report),"Cannot write output");
        results<<"scenario,policy,hot_width,rounds,total_loads,runtime_ns,migration_ns,promotions,demotions,updates,critical_dram_pages,hot_dram_pages,min_cxl_mlp,max_cxl_mlp,alpha,window_ms\n";
        inputs<<"scenario,phase,name,first_page,pages,independent_width,load_misses\n";
        report<<"# Designed variable-MLP streams: PAC versus frequency\n\n"
            <<"Synthetic, pre-filtered LLC-miss streams. This tests PACT-inspired scoring and our lightweight policy; "
            <<"it is not a reproduction of the paper's hardware speedup. "
            <<(selected.empty()?"All fixed scenarios and the control are retained.":"Only the explicitly selected scenario is run; see the full-suite report for controls.")<<"\n\n"
            <<"Decay alpha = "<<alpha<<" for both PAC and frequency: `score_new = alpha * score_old + window_contribution`. "
            <<"Observation window = "<<window_ms<<" ms. "
            <<"All tracked scores decay once per observation, including empty CXL windows.\n\n"
            <<"| Scenario | Frequency ms | PAC ms | Runtime reduction | Promotions F/P | Critical pages in DRAM F/P | Updates F/P |\n"
            <<"|---|---:|---:|---:|---:|---:|---:|\n";
        auto start=std::chrono::steady_clock::now();
        for(size_t scenario=0;scenario<6;++scenario) {
            size_t width=scenario<5?size_t(1)<<scenario:16;
            bool hot_first=scenario<5;
            std::string name=(hot_first?"hot_first_mlp":"critical_first_mlp")+std::to_string(width);
            if(!selected.empty() && name!=selected)continue;
            std::vector<StreamPhase> phases;
            for(size_t round=0;round<rounds;++round) {
                StreamPhase low{"pointer_chain",critical,pages,1,critical_loads};
                StreamPhase high{"independent_hot",hot,pages,width,hot_loads};
                phases.push_back(hot_first?high:low);phases.push_back(hot_first?low:high);
            }
            for(size_t i=0;i<phases.size();++i){const auto& p=phases[i];inputs<<name<<','<<i<<','<<p.name<<','<<p.first<<','<<p.pages<<','<<p.width<<','<<p.loads<<'\n';}
            auto f=simulate_stream(phases,c,rc,"frequency",critical,hot,pages);
            auto p=simulate_stream(phases,c,rc,"pac",critical,hot,pages);
            check(f.result.promotions==rc.promotion_budget && p.result.promotions==rc.promotion_budget,"Both policies must exhaust the same preset promotion budget");
            check(f.result.demotions==p.result.demotions,"Unequal demotions");
            check(std::abs(f.result.migration_ns-p.result.migration_ns)<1e-6,"Unequal copy charges");
            if(width==1){check(f.result.final_dram==p.result.final_dram,"Constant-MLP placement control diverged");
                check(std::abs(f.result.runtime_ns-p.result.runtime_ns)<1e-4,"Constant-MLP runtime control diverged");}
            for(const auto& item:{std::make_pair("frequency",&f),std::make_pair("pac",&p)}) {
                const auto& r=*item.second;double low=1e100,high=0;
                for(const auto& d:r.result.decisions)if(d.tiers[0].misses){low=std::min(low,d.tiers[0].mlp);high=std::max(high,d.tiers[0].mlp);}
                results<<std::setprecision(17)<<name<<','<<item.first<<','<<width<<','<<rounds<<','
                    <<uint64_t(rounds)*(critical_loads+hot_loads)<<','<<r.result.runtime_ns<<','<<r.result.migration_ns<<','
                    <<r.result.promotions<<','<<r.result.demotions<<','<<r.result.decisions.size()<<','
                    <<r.critical_resident<<','<<r.hot_resident<<','<<low<<','<<high<<','<<alpha<<','<<window_ms<<'\n';
                export_decisions(out+"/"+name+"_"+item.first,r.result);
            }
            double reduction=100*(1-p.result.runtime_ns/f.result.runtime_ns);
            report<<std::fixed<<std::setprecision(6)<<"| "<<name<<" | "<<f.result.runtime_ns/1e6<<" | "<<p.result.runtime_ns/1e6
                <<" | "<<reduction<<"% | "<<f.result.promotions<<'/'<<p.result.promotions<<" | "<<f.critical_resident<<'/'<<p.critical_resident
                <<" | "<<f.result.decisions.size()<<'/'<<p.result.decisions.size()<<" |\n";
            results.flush();inputs.flush();report.flush();
            std::cout<<name<<": PAC runtime reduction "<<reduction<<"%; migrations "<<p.result.promotions<<'/'<<f.result.promotions<<'\n'<<std::flush;
        }
        report<<"\nParameters: 90/190 ns DRAM/CXL service (nominal service latency also used as constant k), "<<window_ms<<" ms observations, 1,024-page DRAM "
            <<"(4 MiB), two 1,024-page active groups (8 MiB), and identical cold warmup residency. "
            <<"Hot pages have exactly four times as many load misses. Each scenario alternates "<<rounds
            <<" copies of each phase. Dependencies create the overlap: chain width 1, hot batch width 1/2/4/8/16. "
            <<"Per-tier MLP is calculated from outstanding-load occupancy and active time, never supplied to the scoring function.\n\n"
            <<"Both policies share the bounded-bin policy, reservoir seed, batch cap (128), LRU approximation, "
            <<"and preset total budget of 1,024 promotions. Copying costs 1,409.6 ns per moved page and pauses execution. "
            <<"Once the fixed budget is exhausted, placement stops changing but execution and periodic observations continue. "
            <<"Equal actual promotions, demotions, copy costs and load conservation are checked. "
            <<"Independent analytical checks cover serial, parallel, repeated-cycle, partial-batch and mixed-tier timing. "
            <<"The MLP=1 control must match exactly; reversing the phase order is also retained.\n\n"
            <<"Requests enter after cache filtering: every listed request is assumed to be an LLC miss. "
            <<"No cache-hit rate, CPU instruction count, prefetcher, bandwidth contention or hardware sampling loss is inferred. "
            <<"The independent batches and assumed service times form an analytical workload. "
            <<"The batch barrier is part of that workload, not a simulated CPU pipeline. "
            <<"This makes the phase-level criticality mechanism visible under controlled assumptions. "
            <<"It does not prove that every real workload benefits or that the complete PACT runtime is reproduced.\n\n"
            <<"All source workloads are in [streams.csv](streams.csv); measured decisions and MLP are in the window CSVs. "
            <<"Positive runtime reduction is 100 * (frequency_time - PAC_time) / frequency_time.\n\n"
            <<"Wall seconds: "<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<".\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
