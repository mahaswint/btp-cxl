// Copyright (c) 2026. BSD-3-Clause; see LICENSE.
#ifndef __MEM_CXL_METRICS_HH__
#define __MEM_CXL_METRICS_HH__

#include <memory>
#include <set>
#include <string>

#include "mem/packet.hh"

namespace gem5::cxlmetrics
{
// Retain the Request, not the Packet: receivers may delete a successfully
// transferred packet synchronously. A handle must be acquired BEFORE send().
struct Transaction
{
    uint64_t id;
    RequestPtr request;
    std::string host;
    bool response;
    std::set<std::string> waiting;
    std::string completionPort;
};
using Handle = std::shared_ptr<Transaction>;

void registerNode(const std::string &node, bool endpoint, Tick period,
                  unsigned requests, unsigned responses,
                  AddrRange range = AddrRange());
void fabricPort(const Handle &handle, const std::string &node, Tick period,
                unsigned width, bool response);
void fabricBusy(const std::string &node, bool response, Tick until,
                const std::string &resource = "");
Handle issue(PacketPtr pkt, const std::string &node);
Handle find(PacketPtr pkt);
void event(const Handle &handle, const std::string &kind,
           const std::string &node, uint64_t value = 0);
void block(const std::string &node, const std::string &channel, bool blocked);
void complete(const Handle &handle, const std::string &node);
void phase(const std::string &name, bool begin);
constexpr uint64_t PhaseMagic = 0x53494d43584c;
} // namespace gem5::cxlmetrics
#endif
