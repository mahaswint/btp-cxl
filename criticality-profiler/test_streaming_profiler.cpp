#define main static_profiler_main
#include "trace_profiler.cpp"
#undef main
#include "dynamic_model.h"
#include "streaming_trace.h"
#include <sstream>
void require(bool value) {if(!value) throw std::runtime_error("Streaming equivalence failed");}
int main() {
    std::string bytes;
    for(size_t i=0;i<3200;++i) {
        std::array<unsigned char,64> b{};
        b[10]=uint8_t(1+i%17);b[12]=uint8_t(1+(i+16)%17);
        auto address=[&](size_t offset,uint64_t a){for(size_t j=0;j<8;++j)b[offset+j]=uint8_t(a>>(8*j));};
        address(32,4096+64*((i*13)%1400));
        if(i%3==0) address(40,4096+64*((i*7)%1400));
        if(i%5==0) address(16,4096+64*((i*11)%1400));
        bytes.append(reinterpret_cast<const char*>(b.data()),b.size());
    }
    for(size_t rob:{size_t(1),size_t(3),size_t(32),size_t(192)}) {
        Config c;c.warmup=200;c.rob=rob;c.cache_kib=4;c.ways=1;c.pac_window_ns=2000;
        RuntimeConfig rc;rc.capacity=6;rc.batch=3;rc.reserve=1;
        std::istringstream in(bytes);Cache cache(c);load(in,c.warmup,cache,false);
        auto segment=load(in,3000,cache,true);
        for(const std::string mode:{"cxl","dram","frequency","pac"}) {
            auto reference=dynamic_replay(segment,c,rc,mode);
            std::istringstream streaming(bytes);StreamingSource source(streaming,c);
            auto actual=dynamic_replay_source(source,3000,c,rc,mode);
            require(reference.runtime_ns==actual.runtime_ns);
            require(reference.dram_loads==actual.dram_loads && reference.cxl_loads==actual.cxl_loads);
            require(reference.promotions==actual.promotions && reference.demotions==actual.demotions);
            require(reference.final_dram==actual.final_dram && reference.decisions.size()==actual.decisions.size());
            for(size_t i=0;i<reference.decisions.size();++i) {
                const auto& a=reference.decisions[i];const auto& b=actual.decisions[i];
                require(a.sample_ns==b.sample_ns && a.resume_ns==b.resume_ns);
                require(a.tiers[0].mlp==b.tiers[0].mlp && a.tiers[0].pages==b.tiers[0].pages);
            }
            require(source.last_access.size()<=6*c.rob && source.last_store.size()<=6*c.rob);
        }
    }
    Config c;c.warmup=200;c.cache_kib=4;c.ways=1;c.pac_window_ns=2000;
    RuntimeConfig rc;rc.capacity=6;rc.batch=3;rc.promotion_budget=2;
    for(const std::string mode:{"frequency","pac"}) {
        std::istringstream in(bytes);StreamingSource source(in,c);
        auto result=dynamic_replay_source(source,3000,c,rc,mode);
        require(result.promotions==2 && result.demotions==2);
        rc.promotion_budget=0;std::istringstream zero_in(bytes);StreamingSource zero_source(zero_in,c);
        auto zero=dynamic_replay_source(zero_source,3000,c,rc,mode);
        require(zero.promotions==0 && zero.demotions==0);rc.promotion_budget=2;
    }
    std::cout<<"Streaming/full replay equivalence: register/store dependencies, ROB wrap, cache, migrations and MLP passed.\n";
}
