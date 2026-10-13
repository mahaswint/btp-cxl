#define DYNAMIC_PROFILER_LIBRARY
#include "dynamic_profiler.cpp"
#include "compact_model.h"
#include <chrono>
int main(int argc,char** argv) {
    try {
        std::string trace,cache_path,out="results/compact/run";
        Config c;c.core_ns=1/2.2;c.fast_ns=90;c.slow_ns=190;
        c.pac_k_dram_ns=238.0030811389524/2.2;c.pac_k_cxl_ns=771.0702318170098/2.2;
        RuntimeConfig rc;uint64_t count=0;double fraction=.5;bool prepare=false;
        std::string policy_profile="legacy";
        for(int i=1;i<argc;++i) {
            std::string key=argv[i];if(key=="--prepare"){prepare=true;continue;}
            if(i+1>=argc)throw std::runtime_error("Missing option value");
            std::string value=argv[++i];
            if(key=="--trace")trace=value;else if(key=="--cache")cache_path=value;else if(key=="--out")out=value;
            else if(key=="--instructions")count=integer(value);else if(key=="--warmup")c.warmup=integer(value);
            else if(key=="--window-ns")c.pac_window_ns=positive(value);
            else if(key=="--pac-decay") {rc.pac_decay=nonnegative(value);if(rc.pac_decay>1)throw std::runtime_error("PAC decay must be between 0 and 1");}
            else if(key=="--frequency-decay") {rc.frequency_decay=nonnegative(value);if(rc.frequency_decay>1)throw std::runtime_error("Frequency decay must be between 0 and 1");}
            else if(key=="--capacity-fraction"){fraction=nonnegative(value);if(fraction>1)throw std::runtime_error("Fraction >1");}
            else if(key=="--promotion-budget")rc.promotion_budget=integer(value);
            else if(key=="--batch")rc.batch=integer(value);
            else if(key=="--policy-profile") {
                if(value!="legacy" && value!="paper-all-events" && value!="paper-sampled")throw std::runtime_error("Unknown policy profile");
                policy_profile=value;
                rc.bin_count=value=="legacy"?0:20;rc.bin_scale_threshold=value=="legacy"?20:.7;
                rc.batch=value=="legacy"?64:4096;rc.pebs_period=value=="paper-sampled"?400:1;
            }
            else if(key=="--pebs-period") {rc.pebs_period=integer(value);if(!rc.pebs_period)throw std::runtime_error("Sampling period must be positive");}
            else throw std::runtime_error("Unknown option "+key);
        }
        if(cache_path.empty())throw std::runtime_error("--cache required");
        auto start=std::chrono::steady_clock::now();
        if(prepare) {
            std::ifstream in(trace,std::ios::binary);if(!in)throw std::runtime_error("Cannot open raw trace");
            in.seekg(0,std::ios::end);uint64_t bytes=uint64_t(in.tellg());in.seekg(0);
            if(bytes%64 || bytes/64<=c.warmup)throw std::runtime_error("Invalid raw trace size");
            if(!count)count=bytes/64-c.warmup;
            if(count>bytes/64-c.warmup)throw std::runtime_error("Requested prefix exceeds trace");
            auto g=compile_compact(in,count,c);save_compact(g,cache_path);
            std::cout<<"Prepared "<<g.instructions<<" instructions as "<<g.events.size()<<" scheduled records (memory and epoch fences), "
                <<g.edges.size()<<" dependency edges, "<<g.pages.size()<<" pages; max frontier "<<g.max_frontier<<"\n";
        } else {
            auto g=load_compact(cache_path);rc.capacity=size_t(std::ceil(g.pages.size()*fraction));
            std::ofstream summary(out+".csv"),config(out+"_config.txt");
            if(!summary || !config)throw std::runtime_error("Create output directory first");
            config<<std::setprecision(17)<<"instructions="<<g.instructions<<"\nmemory_events="<<g.events.size()
                <<"\nactual_memory_requests="<<std::count_if(g.events.begin(),g.events.end(),[](const auto& e){return e.load<2;})
                <<"\nconservative_epoch_instructions="<<g.config.rob<<"\nsource_cache="<<cache_path
                <<"\ndependency_edges="<<g.edges.size()<<"\nworking_pages="<<g.pages.size()<<"\ncapacity="<<rc.capacity
                <<"\ncapacity_fraction="<<fraction<<"\nwindow_ns="<<c.pac_window_ns<<"\ncore_ns="<<g.config.core_ns
                <<"\npolicy_profile="<<policy_profile<<"\nbin_count="<<rc.bin_count<<"\nbin_scale_threshold="<<rc.bin_scale_threshold
                <<"\nbatch="<<rc.batch<<"\npebs_period="<<rc.pebs_period
                <<"\npac_decay="<<(rc.pac_decay>=0?rc.pac_decay:c.pac_alpha)<<"\nfrequency_decay="<<(rc.frequency_decay>=0?rc.frequency_decay:c.pac_alpha)
                <<"\ndram_ns="<<c.fast_ns<<"\ncxl_ns="<<c.slow_ns<<"\nmodel=weighted_memory_dag\n";
            summary<<"policy,runtime_ns,promotions,demotions,migration_ns,drain_ns,sampling_ns,decisions,dram_loads,cxl_loads,wall_seconds\n";
            for(const std::string mode:{"cxl","dram","frequency","pac"}) {
                auto begin=std::chrono::steady_clock::now();auto r=replay_compact(g,c,rc,mode);
                double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
                summary<<std::setprecision(17)<<mode<<','<<r.runtime_ns<<','<<r.promotions<<','<<r.demotions<<','<<r.migration_ns
                    <<','<<r.drain_ns<<','<<r.sampling_ns<<','<<r.decisions.size()<<','<<r.dram_loads<<','<<r.cxl_loads<<','<<seconds<<'\n';summary.flush();
                if(mode=="pac" || mode=="frequency")export_decisions(out+"_"+mode,r);
                std::cout<<mode<<": "<<r.runtime_ns/1e6<<" modeled ms, "<<seconds<<" wall seconds\n"<<std::flush;
            }
        }
        std::cout<<"Total wall seconds: "<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<'\n';
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
