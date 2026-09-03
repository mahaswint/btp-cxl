// Copyright (c) 2026. BSD-3-Clause; see LICENSE.
#include "mem/cxl_metrics.hh"

#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <vector>

#include "base/logging.hh"
#include "sim/core.hh"
#include "sim/cur_tick.hh"
#include "sim/sim_exit.hh"

namespace gem5::cxlmetrics
{
namespace
{
std::string
quote(const std::string &s)
{
    std::ostringstream out;
    out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4)
                             << std::setfill('0') << unsigned(c);
        else out << c;
    }
    return out.str() + '"';
}

struct Recorder
{
    std::ofstream stream;
    uint64_t next = 0;
    std::vector<std::pair<AddrRange, std::string>> ranges;
    std::set<std::string> fabricPorts;
    std::set<std::string> fabricParents;
    std::map<const Request *, Handle> pending;
    std::map<std::pair<std::string, std::string>, bool> blocked;

    Recorder()
    {
        const char *path = std::getenv("SIMCXL_METRICS_TRACE");
        if (!path || !*path) return;
        stream.open(path);
        fatal_if(!stream, "Cannot open CXL metrics trace %s", path);
        write("\"event\":\"start\",\"tick_frequency\":" +
              std::to_string(sim_clock::Frequency));
        registerExitCallback([this] {
            write("\"event\":\"end\"");
            stream.flush();
        });
    }

    void write(const std::string &fields)
    {
        if (stream.is_open()) {
            stream << "{\"tick\":" << curTick() << ',' << fields << "}\n";
            fatal_if(!stream, "Writing CXL metrics trace failed");
        }
    }
};

Recorder &recorder() { static Recorder instance; return instance; }
} // anonymous namespace

void
registerNode(const std::string &node, bool endpoint, Tick period,
             unsigned requests, unsigned responses, AddrRange range)
{
    auto &r = recorder();
    if (!r.stream.is_open()) return;
    if (endpoint) r.ranges.emplace_back(range, node);
    r.write("\"event\":\"node\",\"node\":" + quote(node) +
        ",\"endpoint\":" + (endpoint ? "true" : "false") +
        ",\"clock_period\":" + std::to_string(period) +
        ",\"request_capacity\":" + std::to_string(requests) +
        ",\"response_capacity\":" + std::to_string(responses) +
        ",\"capacity_bytes\":" + std::to_string(endpoint ? range.size() : 0));
}

Handle
find(PacketPtr pkt)
{
    auto &r = recorder();
    if (!r.stream.is_open()) return {};
    auto it = r.pending.find(pkt->req.get());
    return it == r.pending.end() ? Handle{} : it->second;
}

Handle
issue(PacketPtr pkt, const std::string &node)
{
    auto &r = recorder();
    if (!r.stream.is_open()) return {};
    if (auto existing = find(pkt)) return existing;
    std::string endpoint;
    for (const auto &[range, name] : r.ranges) {
        if (range.contains(pkt->getAddr())) {
            fatal_if(!endpoint.empty(), "Overlapping CXL endpoint ranges");
            endpoint = name;
        }
    }
    if (endpoint.empty() || !(pkt->isRead() || pkt->isWrite())) return {};
    auto h = std::make_shared<Transaction>(Transaction{
        ++r.next, pkt->req, node, pkt->needsResponse(), {}, {}});
    r.pending.emplace(pkt->req.get(), h);
    const bool atomic = pkt->isAtomicOp() || pkt->req->isSwap();
    r.write("\"event\":\"issue\",\"id\":" + std::to_string(h->id) +
        ",\"node\":" + quote(node) + ",\"op\":" +
        quote(atomic ? "atomic" : pkt->isRead() ? "read" : "write") +
        ",\"bytes\":" + std::to_string(pkt->getSize()) +
        ",\"response\":" + (h->response ? "true" : "false"));
    event(h, "endpoint", endpoint);
    return h;
}

void
event(const Handle &h, const std::string &kind, const std::string &node,
      uint64_t value)
{
    if (!h) return;
    recorder().write("\"event\":" + quote(kind) + ",\"node\":" +
        quote(node) + ",\"id\":" + std::to_string(h->id) +
        ",\"value\":" + std::to_string(value));
    if (kind == "request_dequeue" || kind == "response_dequeue")
        h->waiting.erase(node + (kind == "request_dequeue" ? ".request" : ".response"));
    if (kind == "unacknowledged")
        recorder().pending.erase(h->request.get());
}

void
fabricPort(const Handle &h, const std::string &node, Tick period,
           unsigned width, bool response)
{
    if (!h) return;
    auto &r = recorder();
    if (r.fabricPorts.insert(node).second) {
        r.fabricParents.insert(node.substr(0, node.rfind(".port.")));
        registerNode(node, false, period, 0, 0);
        r.write("\"event\":\"fabric_config\",\"node\":" + quote(node) +
                ",\"width_bytes\":" + std::to_string(width));
    }
    auto key = node + (response ? ".response" : ".request");
    if (h->waiting.insert(key).second)
        event(h, response ? "response_enqueue" : "request_enqueue", node);
}

void
fabricBusy(const std::string &node, bool response, Tick until,
           const std::string &resource)
{
    auto &r = recorder();
    if (!r.fabricParents.count(node.substr(0, node.rfind(".port."))) ||
        until <= curTick()) return;
    r.write("\"event\":\"busy\",\"node\":" + quote(node) +
            ",\"direction\":" + quote(response ? "response" : "request") +
            ",\"resource\":" + quote(resource.empty() ? node : resource) +
            ",\"until\":" + std::to_string(until));
}

void
block(const std::string &node, const std::string &channel, bool blocked)
{
    auto &r = recorder();
    if (!r.stream.is_open()) return;
    auto &previous = r.blocked[{node, channel}];
    if (previous == blocked) return;
    previous = blocked;
    r.write("\"event\":\"block\",\"node\":" + quote(node) +
        ",\"channel\":" + quote(channel) +
        ",\"blocked\":" + (blocked ? "true" : "false"));
}

void
complete(const Handle &h, const std::string &node)
{
    if (!h || node != h->host) return;
    event(h, "complete", node);
    recorder().pending.erase(h->request.get());
}

void
phase(const std::string &name, bool begin)
{
    recorder().write("\"event\":" + quote(begin ? "phase_begin" : "phase_end") +
                     ",\"name\":" + quote(name));
}
} // namespace gem5::cxlmetrics
