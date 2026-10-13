#pragma once
#include <random>

struct RuntimeConfig {
    size_t capacity=256, batch=64, reserve=0;
    size_t promotion_budget=std::numeric_limits<size_t>::max();
    size_t bin_count=0,pebs_period=1;
    double bin_scale_threshold=20;
    // Negative preserves --alpha's legacy behavior; nonnegative overrides PAC only.
    double pac_decay=-1;
    double frequency_decay=-1;
    double copy_gbps=10, move_overhead_ns=1000, sampling_cost_ns=0;
    uint32_t seed=1;
};
struct TierStats {
    uint64_t misses=0;
    double area=0,active=0,mlp=0,stalls=0;
    std::map<Page,uint64_t> pages;
    std::vector<Page> sample_order;
};
// No interval beyond the current observation time contributes to counters.
std::array<TierStats,2> observe(const std::vector<Request>& requests,double lo,double hi,const Config& c) {
    std::array<TierStats,2> stats;
    std::array<std::vector<std::pair<double,double>>,2> intervals;
    for(const auto& r:requests) {
        auto& s=stats[r.dram?1:0];
        if(r.start>=lo && r.start<hi) {++s.misses;++s.pages[r.page];}
        double start=std::max(lo,r.start),end=std::min(hi,r.end);
        if(end>start) {s.area+=end-start;intervals[r.dram?1:0].push_back({start,end});}
    }
    for(size_t tier=0;tier<2;++tier) {
        auto& s=stats[tier];auto& ranges=intervals[tier];
        std::sort(ranges.begin(),ranges.end());
        double covered=lo;
        for(const auto& r:ranges) {s.active+=std::max(0.0,r.second-std::max(covered,r.first));covered=std::max(covered,r.second);}
        if(s.active>0) {
            s.mlp=s.area/s.active;
            double k=tier?(c.pac_k_dram_ns>0?c.pac_k_dram_ns:c.fast_ns):
                (c.pac_k_cxl_ns>0?c.pac_k_cxl_ns:c.slow_ns);
            s.stalls=k*s.misses/s.mlp;
        }
    }
    return stats;
}
struct Move { Page page; bool promotion; };
struct Plan {
    std::vector<Move> moves;
    double bin_width=0,cutoff=0;
    size_t candidates=0;
};
struct RuntimePolicy {
    RuntimeConfig config;
    Placement dram;
    std::map<Page,double> scores;
    std::map<Page,uint64_t> recency;
    uint64_t clock=0;
    size_t initial_allocations=0;
    std::mt19937 rng;
    std::vector<double> access_reservoir;
    uint64_t reservoir_seen=0;
    explicit RuntimePolicy(const RuntimeConfig& r): config(r),rng(r.seed) {}
    // Both policies start with identical first-touch DRAM admission.
    void touch(Page page) {
        if(!recency.count(page) && initial_allocations<config.capacity && dram.size()<config.capacity) {
            dram.insert(page);++initial_allocations;
        }
        recency[page]=++clock;
    }
    void update(const TierStats& slow,const Config& c,bool pac) {
        double override_decay=pac?config.pac_decay:config.frequency_decay;
        double decay=override_decay>=0?override_decay:c.pac_alpha;
        for(auto& s:scores) s.second*=decay;
        // Historical reservoir values must stay in the same decayed score units.
        for(auto& value:access_reservoir)value*=decay;
        uint64_t observations=0;for(const auto& page:slow.pages)observations+=page.second;
        if(!observations)return;
        const double unit=pac?slow.stalls/double(observations):1;
        if(config.bin_count) {
            auto sample=[&](Page page) {
                double score=(scores[page]+=unit);++reservoir_seen;
                if(access_reservoir.size()<100)access_reservoir.push_back(score);
                else {std::uniform_int_distribution<uint64_t> pick(0,reservoir_seen-1);auto j=pick(rng);
                    if(j<100)access_reservoir[size_t(j)]=score;}
            };
            if(!slow.sample_order.empty())for(Page page:slow.sample_order)sample(page);
            else for(const auto& page:slow.pages)for(uint64_t j=0;j<page.second;++j)sample(page.first);
            return;
        }
        for(const auto& page:slow.pages) {
            double contribution=unit*double(page.second);
            scores[page.first]+=contribution;
        }
    }
    Plan decide() {
        Plan plan;
        std::vector<double> reservoir;
        size_t seen=0;
        // Reservoir sample of up to 100 current slow-page scores, in page-ID
        // order for deterministic random sampling; no global score ranking.
        for(const auto& p:scores) if(!dram.count(p.first) && p.second>0) {
            ++seen;
            if(reservoir.size()<100) reservoir.push_back(p.second);
            else {std::uniform_int_distribution<size_t> pick(0,seen-1);size_t j=pick(rng);
                if(j<100) reservoir[j]=p.second;}
        }
        std::vector<Page> candidates;
        if(config.bin_count && !access_reservoir.empty())reservoir=access_reservoir;
        if(seen && config.batch && config.capacity>config.reserve) {
            std::sort(reservoir.begin(),reservoir.end());
            auto quantile=[&](double q){
                double x=q*(reservoir.size()-1);size_t low=size_t(x),high=std::min(low+1,reservoir.size()-1);
                return reservoir[low]+(x-low)*(reservoir[high]-reservoir[low]);
            };
            double width=2*(quantile(.75)-quantile(.25))/std::cbrt(double(config.bin_count?scores.size():seen));
            double maximum=0;
            for(const auto& p:scores) if(!dram.count(p.first)) maximum=std::max(maximum,p.second);
            if(!(width>0)) width=std::max(maximum/double(config.bin_count?config.bin_count:20),1e-12);
            auto gather=[&](double w){
                candidates.clear();double top=std::floor(maximum/w);
                if(config.bin_count)top=std::min(top,double(config.bin_count-1));
                plan.cutoff=top*w;
                for(const auto& p:scores) if(!dram.count(p.first) && p.second>0) {
                    double index=std::floor(p.second/w);
                    if(config.bin_count)index=std::min(index,double(config.bin_count-1));
                    if(index==top)candidates.push_back(p.first);
                }
            };
            gather(width);
            // Legacy pressure threshold is a model assumption; bounded profiles
            // use the artifact's 0.7 but approximate ring occupancy by candidates.
            width*=double(config.bin_count?scores.size():seen)/std::max(size_t(1),candidates.size())>config.bin_scale_threshold?2:.5;
            gather(width);
            plan.bin_width=width;plan.candidates=candidates.size();
            std::sort(candidates.begin(),candidates.end(),[&](Page a,Page b){
                if(scores.at(a)!=scores.at(b)) return scores.at(a)>scores.at(b);
                return a<b;
            });
            candidates.resize(std::min({candidates.size(),config.batch,config.capacity-config.reserve,config.promotion_budget}));
        }
        size_t required=dram.size()+candidates.size()+std::min(config.reserve,config.capacity);
        size_t demote=required>config.capacity?required-config.capacity:0;
        demote=std::min(demote,dram.size());
        std::vector<Page> victims;
        if(demote)victims.assign(dram.begin(),dram.end());
        std::partial_sort(victims.begin(),victims.begin()+demote,victims.end(),[&](Page a,Page b){
            if(recency.at(a)!=recency.at(b)) return recency.at(a)<recency.at(b);
            return a<b;
        });
        for(size_t i=0;i<demote;++i) {dram.erase(victims[i]);plan.moves.push_back({victims[i],false});}
        for(Page page:candidates) {
            if(dram.size()>=config.capacity) throw std::runtime_error("DRAM capacity exceeded");
            dram.insert(page);plan.moves.push_back({page,true});
        }
        config.promotion_budget-=candidates.size();
        return plan;
    }
};
struct Decision {
    double sample_ns=0,resume_ns=0,drain_ns=0,move_ns=0;
    std::array<TierStats,2> tiers;
    Plan plan;
    size_t resident=0;
};
struct DynamicResult {
    double runtime_ns=0,migration_ns=0,drain_ns=0,sampling_ns=0;
    size_t promotions=0,demotions=0;
    uint64_t dram_loads=0,cxl_loads=0;
    std::vector<Decision> decisions;
    Placement final_dram;
};
// Event-driven execution: dependencies survive sampling and migration points.
// Modes: pac, frequency, cxl (all slow), dram (unlimited all fast).
struct SegmentSource {
    const Segment& segment;
    const Node& admit(size_t i,size_t) {return segment.nodes[i];}
    const Node& node(size_t i) const {return segment.nodes[i];}
    void retire(size_t) {}
};
template<class Source>
DynamicResult dynamic_replay_source(Source& source,size_t n,const Config& c,const RuntimeConfig& rc,const std::string& mode) {
    const bool managed=mode=="pac" || mode=="frequency";
    const bool periodic=managed && rc.capacity>0 && (rc.batch>0 || rc.reserve>0);
    if(!managed && mode!="cxl" && mode!="dram") throw std::runtime_error("Invalid runtime mode");
    RuntimePolicy policy(rc);
    // Retired dependencies are already satisfied. Only admitted work needs links.
    std::vector<std::vector<size_t>> successors(c.rob);
    std::vector<size_t> remaining(c.rob);
    std::vector<bool> done(c.rob,false);
    using Completion=std::pair<double,size_t>;
    std::priority_queue<Completion,std::vector<Completion>,std::greater<Completion>> completions;
    std::priority_queue<size_t,std::vector<size_t>,std::greater<size_t>> ready_compute,ready_memory;
    auto ready=[&](size_t i){
        if(source.node(i).misses.empty()) ready_compute.push(i);else ready_memory.push(i);
    };
    std::vector<Request> requests;
    size_t next=0,retired=0,completed=0,occupied=0;
    double now=0,next_admit=0,next_sample=c.pac_window_ns,last_sample=0,drain_start=0;
    bool draining=false;
    DynamicResult result;
    auto execute=[&](size_t i){
        const auto& node=source.node(i);
        double cursor=now+c.core_ns+node.hits*c.hit_ns;
        if(!node.misses.empty()) ++occupied;
        for(size_t m=0;m<node.misses.size();++m) {
            Page page=node.misses[m];
            if(managed) policy.touch(page);
            bool dram=mode=="dram" || (managed && policy.dram.count(page));
            double end=cursor+(dram?c.fast_ns:c.slow_ns);
            if(node.miss_loads.empty() || node.miss_loads[m]) {
                if(managed) requests.push_back({cursor,end,page,dram});
                if(dram) ++result.dram_loads;else ++result.cxl_loads;
            }
            cursor=end;
        }
        completions.push({cursor,i});
    };
    while(completed<n) {
        // Finish events first: release resources and awaken dependent work.
        while(!completions.empty() && completions.top().first<=now) {
            size_t i=completions.top().second;completions.pop();done[i%c.rob]=true;++completed;
            if(!source.node(i).misses.empty()) --occupied;
            for(size_t child:successors[i%c.rob]) {--remaining[child%c.rob];if(!remaining[child%c.rob]) ready(child);}
            successors[i%c.rob].clear();
        }
        while(retired<next && done[retired%c.rob]) {source.retire(retired);++retired;}
        if(completed==n) break; // Never migrate after workload completion.
        if(periodic && !draining && now>=next_sample) {draining=true;drain_start=now;}
        if(draining && completions.empty()) {
            Decision decision;decision.sample_ns=now;decision.drain_ns=now-drain_start;
            decision.tiers=observe(requests,last_sample,now,c);
            policy.update(decision.tiers[0],c,mode=="pac");
            decision.plan=policy.decide();
            double cost=rc.move_overhead_ns+4096/rc.copy_gbps;
            for(const auto& move:decision.plan.moves) {
                if(move.promotion) ++result.promotions;else ++result.demotions;
                decision.move_ns+=cost;
            }
            result.drain_ns+=decision.drain_ns;result.migration_ns+=decision.move_ns;
            result.sampling_ns+=rc.sampling_cost_ns;
            decision.resident=policy.dram.size();
            last_sample=now;
            now+=decision.move_ns+rc.sampling_cost_ns;
            decision.resume_ns=now;
            result.decisions.push_back(std::move(decision));
            requests.clear(); // All admitted instructions have drained.
            next_admit=std::max(next_admit,now);next_sample=now+c.pac_window_ns;
            draining=false;
        }
        if(!draining) {
            if(next<n && now>=next_admit && next-retired<c.rob) {
                size_t count=0;
                while(next<n && next-retired<c.rob && count<c.width) {
                    size_t slot=next%c.rob;
                    done[slot]=false;remaining[slot]=0;successors[slot].clear();
                    const auto& node=source.admit(next,retired);
                    for(int p:node.deps) {
                        if(p<0 || size_t(p)>=next) throw std::runtime_error("Invalid dependency");
                        if(size_t(p)>=retired && !done[size_t(p)%c.rob]) {
                            ++remaining[slot];successors[size_t(p)%c.rob].push_back(next);
                        }
                    }
                    if(!remaining[slot]) ready(next);
                    ++next;++count;
                }
                next_admit=now+c.core_ns;
            }
            while(!ready_compute.empty()) {size_t i=ready_compute.top();ready_compute.pop();execute(i);}
            while(!ready_memory.empty() && occupied<c.mlp) {size_t i=ready_memory.top();ready_memory.pop();execute(i);}
        }
        double event=std::numeric_limits<double>::infinity();
        if(!completions.empty()) event=std::min(event,completions.top().first);
        if(!draining) {
            if(next<n && next-retired<c.rob) event=std::min(event,next_admit);
            if(periodic) event=std::min(event,next_sample);
        }
        if(!std::isfinite(event) || event<=now) throw std::runtime_error("Runtime event scheduler stalled");
        now=event;
    }
    result.runtime_ns=now;result.final_dram=policy.dram;
    return result;
}
DynamicResult dynamic_replay(const Segment& segment,const Config& c,const RuntimeConfig& rc,const std::string& mode) {
    SegmentSource source{segment};
    return dynamic_replay_source(source,segment.nodes.size(),c,rc,mode);
}
