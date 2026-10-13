// Reuse the standard trace reader and analytical memory model definitions.
#define main static_profiler_main
#include "trace_profiler.cpp"
#undef main
#include "dynamic_model.h"
#include "streaming_trace.h"

double nonnegative(const std::string& value) {
    size_t used=0;double result=std::stod(value,&used);
    if(used!=value.size() || !std::isfinite(result) || result<0)
        throw std::runtime_error("Expected finite nonnegative value");
    return result;
}
void export_decisions(const std::string& path,const DynamicResult& result) {
    std::ofstream out(path+"_windows.csv"),moves(path+"_moves.csv");
    if(!out || !moves) throw std::runtime_error("Cannot write runtime logs");
    out<<"window,sample_ns,resume_ns,drain_ns,migration_ns,dram_pages,bin_width,cutoff,candidates,cxl_misses,cxl_mlp,dram_misses,dram_mlp,cxl_page_samples,cxl_stall_estimate_ns\n";
    moves<<"window,page,direction\n";
    for(size_t i=0;i<result.decisions.size();++i) {
        const auto& d=result.decisions[i];
        uint64_t samples=0;for(const auto& p:d.tiers[0].pages)samples+=p.second;
        out<<std::setprecision(17)<<i<<','<<d.sample_ns<<','<<d.resume_ns<<','<<d.drain_ns<<','<<d.move_ns<<','
            <<d.resident<<','<<d.plan.bin_width<<','<<d.plan.cutoff<<','<<d.plan.candidates<<','
            <<d.tiers[0].misses<<','<<d.tiers[0].mlp<<','<<d.tiers[1].misses<<','<<d.tiers[1].mlp<<','<<samples<<','<<d.tiers[0].stalls<<'\n';
        for(const auto& m:d.plan.moves) moves<<i<<','<<m.page<<','<<(m.promotion?"CXL_to_DRAM":"DRAM_to_CXL")<<'\n';
    }
    std::ofstream placement(path+"_final_pages.csv");
    if(!placement) throw std::runtime_error("Cannot write final placement");
    placement<<"page\n";for(Page page:result.final_dram) placement<<page<<'\n';
}
#ifndef DYNAMIC_PROFILER_LIBRARY
int main(int argc,char** argv) {
    try {
        Config c;RuntimeConfig rc;
        std::string trace,prefix="results/dynamic/run";
        size_t instructions=1000000;
        bool streaming=false;
        double capacity_fraction=0;
        for(int i=1;i<argc;++i) {
            std::string option=argv[i];
            if(option=="--help") {
                std::cout<<"dynamic_profiler --trace raw.bin --out existing-directory/name\n"
                    <<" --instructions N --warmup N --capacity N --window-ns N --batch N --reserve N\n"
                    <<" --migration-gbps N --move-overhead-ns N --sampling-cost-ns N --alpha N --seed N\n"
                    <<" --dram-ns N --cxl-ns N --mlp N --rob N --width N --cache-kib N --ways N\n";
                std::cout<<" --core-ns N --hit-ns N --pac-k-dram-ns N --pac-k-cxl-ns N\n";
                std::cout<<" --streaming 0|1 --capacity-fraction fraction-of-accessed-pages\n";
                std::cout<<" --promotion-budget N (total promotions per policy)\n";
                std::cout<<" --pac-decay N (0..1, PAC-only retention per update)\n";
                std::cout<<" --frequency-decay N (optional matched-recency control)\n";
                return 0;
            }
            if(i+1>=argc) throw std::runtime_error("Missing value for "+option);
            std::string value=argv[++i];
            if(option=="--trace") trace=value;
            else if(option=="--out") prefix=value;
            else if(option=="--instructions") instructions=integer(value);
            else if(option=="--warmup") c.warmup=integer(value);
            else if(option=="--capacity") rc.capacity=integer(value);
            else if(option=="--streaming") {size_t value_n=integer(value);if(value_n>1) throw std::runtime_error("Expected 0 or 1");streaming=value_n;}
            else if(option=="--capacity-fraction") {capacity_fraction=positive(value);if(capacity_fraction>1) throw std::runtime_error("Fraction must be <= 1");}
            else if(option=="--window-ns") c.pac_window_ns=positive(value);
            else if(option=="--batch") rc.batch=integer(value);
            else if(option=="--promotion-budget") rc.promotion_budget=integer(value);
            else if(option=="--reserve") rc.reserve=integer(value);
            else if(option=="--migration-gbps") rc.copy_gbps=positive(value);
            else if(option=="--move-overhead-ns") rc.move_overhead_ns=nonnegative(value);
            else if(option=="--sampling-cost-ns") rc.sampling_cost_ns=nonnegative(value);
            else if(option=="--alpha") c.pac_alpha=nonnegative(value);
            else if(option=="--pac-decay") {rc.pac_decay=nonnegative(value);if(rc.pac_decay>1)throw std::runtime_error("PAC decay must be between 0 and 1");}
            else if(option=="--frequency-decay") {rc.frequency_decay=nonnegative(value);if(rc.frequency_decay>1)throw std::runtime_error("Frequency decay must be between 0 and 1");}
            else if(option=="--seed") {
                size_t seed=integer(value);if(seed>std::numeric_limits<uint32_t>::max()) throw std::runtime_error("Seed too large");
                rc.seed=uint32_t(seed);
            }
            else if(option=="--dram-ns") c.fast_ns=positive(value);
            else if(option=="--cxl-ns") c.slow_ns=positive(value);
            else if(option=="--core-ns") c.core_ns=positive(value);
            else if(option=="--hit-ns") c.hit_ns=positive(value);
            else if(option=="--pac-k-dram-ns") c.pac_k_dram_ns=positive(value);
            else if(option=="--pac-k-cxl-ns") c.pac_k_cxl_ns=positive(value);
            else if(option=="--mlp") c.mlp=integer(value);
            else if(option=="--rob") c.rob=integer(value);
            else if(option=="--width") c.width=integer(value);
            else if(option=="--cache-kib") c.cache_kib=integer(value);
            else if(option=="--ways") c.ways=integer(value);
            else throw std::runtime_error("Unknown option: "+option);
        }
        if(trace.empty() || !instructions || instructions>size_t(std::numeric_limits<int>::max()) ||
            !c.cache_kib || c.cache_kib>1048576 || !c.ways || c.ways>1024 || c.cache_kib*1024%(64*c.ways) ||
            !c.rob || !c.width || !c.mlp || c.mlp>1048576 || c.slow_ns<c.fast_ns ||
            c.pac_alpha>1 || rc.reserve>rc.capacity)
            throw std::runtime_error("Invalid runtime configuration");
        std::ifstream in(trace,std::ios::binary);
        if(!in) throw std::runtime_error("Cannot open trace");
        size_t working_pages=0;
        if(capacity_fraction>0) {
            std::set<Page> pages;
            for(size_t i=0;i<c.warmup;++i) read(in);
            for(size_t i=0;i<instructions;++i) {
                auto instruction=read(in);
                for(auto address:instruction.loads) if(address) pages.insert(address/4096);
                for(auto address:instruction.stores) if(address) pages.insert(address/4096);
            }
            working_pages=pages.size();rc.capacity=size_t(std::ceil(working_pages*capacity_fraction));
            if(rc.reserve>rc.capacity) throw std::runtime_error("Reserve exceeds scaled capacity");
            in.clear();in.seekg(0);
        }
        Segment segment;
        if(!streaming) {Cache cache(c);load(in,c.warmup,cache,false);segment=load(in,instructions,cache,true);}
        std::ofstream summary(prefix+".csv"),config(prefix+"_config.txt");
        if(!summary || !config) throw std::runtime_error("Create output directory first");
        config<<std::setprecision(17)<<"trace="<<trace<<"\ninstructions="<<instructions<<"\nwarmup="<<c.warmup
            <<"\ncapacity="<<rc.capacity<<"\nwindow_ns="<<c.pac_window_ns<<"\nbatch="<<rc.batch<<"\nreserve="<<rc.reserve
            <<"\npromotion_budget="<<rc.promotion_budget
            <<"\npac_decay="<<(rc.pac_decay>=0?rc.pac_decay:c.pac_alpha)<<"\nfrequency_decay="<<(rc.frequency_decay>=0?rc.frequency_decay:c.pac_alpha)
            <<"\nmigration_gbps="<<rc.copy_gbps<<"\nmove_overhead_ns="<<rc.move_overhead_ns
            <<"\nsampling_cost_ns="<<rc.sampling_cost_ns<<"\nalpha="<<c.pac_alpha<<"\nseed="<<rc.seed
            <<"\ndram_ns="<<c.fast_ns<<"\ncxl_ns="<<c.slow_ns<<"\nmlp_slots="<<c.mlp<<"\nrob="<<c.rob
            <<"\nwidth="<<c.width<<"\ncache_kib="<<c.cache_kib<<"\nways="<<c.ways
            <<"\ncore_ns="<<c.core_ns<<"\nhit_ns="<<c.hit_ns
            <<"\npac_k_dram_ns="<<(c.pac_k_dram_ns>0?c.pac_k_dram_ns:c.fast_ns)
            <<"\npac_k_cxl_ns="<<(c.pac_k_cxl_ns>0?c.pac_k_cxl_ns:c.slow_ns)
            <<"\nstreaming="<<streaming<<"\nworking_pages="<<working_pages<<"\ncapacity_fraction="<<capacity_fraction
            <<"\nmigration_model=synchronous_drain_and_copy\n";
        summary<<"policy,runtime_ns,promotions,demotions,migration_ns,drain_ns,sampling_ns,decisions,dram_loads,cxl_loads\n";
        double frequency=0,pac=0;
        for(const std::string mode:{"cxl","dram","frequency","pac"}) {
            DynamicResult result;
            if(streaming) {
                in.clear();in.seekg(0);
                StreamingSource source(in,c);
                result=dynamic_replay_source(source,instructions,c,rc,mode);
            } else result=dynamic_replay(segment,c,rc,mode);
            summary<<std::setprecision(17)<<mode<<','<<result.runtime_ns<<','<<result.promotions<<','<<result.demotions<<','
                <<result.migration_ns<<','<<result.drain_ns<<','<<result.sampling_ns<<','<<result.decisions.size()<<','
                <<result.dram_loads<<','<<result.cxl_loads<<'\n';
            summary.flush();config.flush();
            if(mode=="frequency") frequency=result.runtime_ns;
            if(mode=="pac") pac=result.runtime_ns;
            if(mode=="pac" || mode=="frequency") export_decisions(prefix+"_"+mode,result);
            std::cout<<std::fixed<<std::setprecision(3)<<mode<<": "<<result.runtime_ns/1e6<<" ms; "
                <<result.promotions<<" promotions, "<<result.demotions<<" demotions; migration "<<result.migration_ns/1e6<<" ms\n";
        }
        std::cout<<"PAC runtime reduction vs dynamic frequency: "<<100*(frequency-pac)/frequency<<"%\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"Error: "<<e.what()<<'\n';return 1;}
}
#endif
