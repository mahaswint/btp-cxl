#pragma once
// Trace-order cache outcomes and dependencies, with only live ROB state retained.
struct StreamingSource {
    std::istream& in;
    Cache cache;
    std::vector<Node> ring;
    std::vector<std::vector<uint64_t>> lines;
    std::array<int,256> producers;
    std::unordered_map<uint64_t,int> last_store,last_access;
    explicit StreamingSource(std::istream& stream,const Config& c):
        in(stream),cache(c),ring(c.rob),lines(c.rob) {
        producers.fill(NONE);
        load(in,c.warmup,cache,false);
    }
    const Node& admit(size_t i,size_t retired) {
        auto instruction=read(in);
        auto& n=ring[i%ring.size()];n=Node{};
        auto& touched=lines[i%ring.size()];touched.clear();
        auto dependency=[&](int p){if(p!=NONE && size_t(p)>=retired) n.deps.push_back(p);};
        for(auto r:instruction.src) if(r) dependency(producers[r]);
        auto access=[&](uint64_t address,bool store) {
            if(!address) return;
            uint64_t line=address/64;touched.push_back(line);
            if(cache.miss(address)) {n.misses.push_back(address/4096);n.miss_loads.push_back(!store);}
            else ++n.hits;
            auto previous=last_store.find(line);
            if(previous!=last_store.end() && previous->second!=int(i)) dependency(previous->second);
            if(store) {
                auto previous_access=last_access.find(line);
                if(previous_access!=last_access.end() && previous_access->second!=int(i)) dependency(previous_access->second);
                last_store[line]=int(i);
            }
            last_access[line]=int(i);
        };
        for(auto address:instruction.loads) access(address,false);
        for(auto address:instruction.stores) access(address,true);
        for(auto r:instruction.dst) if(r) producers[r]=int(i);
        std::sort(n.deps.begin(),n.deps.end());
        n.deps.erase(std::unique(n.deps.begin(),n.deps.end()),n.deps.end());
        return n;
    }
    const Node& node(size_t i) const {return ring[i%ring.size()];}
    void retire(size_t i) {
        for(uint64_t line:lines[i%ring.size()]) {
            auto erase=[&](auto& history){auto p=history.find(line);if(p!=history.end() && p->second==int(i)) history.erase(p);};
            erase(last_store);erase(last_access);
        }
    }
};
