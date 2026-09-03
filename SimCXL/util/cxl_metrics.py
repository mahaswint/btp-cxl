#!/usr/bin/env python3
"""Collect and report simulator-internal CXL timing metrics (standard library only)."""
import argparse
from collections import Counter, defaultdict
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import time
import uuid


DIRECTIONS = ("read", "write")


def distribution(hist):
    """Exact nearest-rank quantiles; histogram weights may be elapsed ticks."""
    hist = {int(k): v for k, v in hist.items() if v > 0}
    count = sum(hist.values())
    result = {"count": count, "min": None, "mean": None,
              "p50": None, "p95": None, "p99": None, "max": None,
              "histogram": dict(sorted(hist.items()))}
    if not count:
        return result
    result.update(min=min(hist), max=max(hist),
                  mean=sum(k * v for k, v in hist.items()) / count)
    for label, p in (("p50", .50), ("p95", .95), ("p99", .99)):
        target, accumulated = max(1, math.ceil(count * p)), 0
        for value, weight in sorted(hist.items()):
            accumulated += weight
            if accumulated >= target:
                result[label] = value
                break
    return result


def clipped(intervals, begin, end):
    return [(max(a, begin), min(b, end)) for a, b in intervals
            if max(a, begin) < min(b, end)]


def union(intervals):
    merged = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def duration(intervals):
    return sum(b - a for a, b in union(intervals))


def intersection(left, right):
    """Intersect interval unions without scanning all busy intervals per request."""
    left, right = union(left), union(right)
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if a < b:
            result.append((a, b))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def behavior(read, write, begin, end):
    r = duration(clipped(read, begin, end))
    w = duration(clipped(write, begin, end))
    either = duration(clipped(read + write, begin, end))
    both = r + w - either
    return {"read_only_time": r - both, "write_only_time": w - both,
            "bidirectional_time": both, "idle_time": end - begin - either,
            "bidirectional_overlap": both / either if either else 0.0}


def queue_hist(events, begin, end):
    """Events are (tick, read_delta, write_delta), including pre-phase history."""
    depths = [0, 0]
    hist = [Counter(), Counter(), Counter()]
    last = begin
    maximum = [0, 0, 0]
    # Collapse changes at the same tick; no artificial ordering-dependent peaks.
    changes = defaultdict(lambda: [0, 0])
    for tick, rd, wr in events:
        if tick <= end:
            changes[tick][0] += rd
            changes[tick][1] += wr
    for tick, delta in sorted(changes.items()):
        if tick > begin:
            for h, value in zip(hist, (*depths, sum(depths))):
                h[value] += tick - last
            last = tick
        depths = [a + b for a, b in zip(depths, delta)]
        if min(depths) < 0:
            raise ValueError("Negative queue depth: malformed/incomplete trace")
        if begin <= tick < end:
            maximum = [max(a, b) for a, b in zip(maximum, (*depths, sum(depths)))]
    for h, value in zip(hist, (*depths, sum(depths))):
        h[value] += end - last
    result = [distribution(h) for h in hist]
    for item, peak in zip(result, maximum):
        item["max"] = max(item["max"] or 0, peak)
    return result


def walk_config(obj):
    if isinstance(obj, dict):
        if "path" in obj and "type" in obj:
            yield obj["path"], obj
        for value in obj.values():
            yield from walk_config(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_config(value)


def node_metadata(node, config):
    c = config.get(node["node"], {})
    # A CXL endpoint's backend can be SimpleMemory, DRAM, or NVM. Preserve
    # actual configured timing parameters instead of inventing one medium delay.
    memory = {}
    pending = [node["node"]]
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        child = config.get(path, {})
        for memory_path, candidate in config.items():
            if memory_path == path or memory_path.startswith(path + "."):
                if "range" in candidate and any(k in candidate for k in ("latency", "tCL", "tRCD")):
                    memory[memory_path] = {k: candidate[k] for k in
                        ("type", "range", "latency", "latency_var", "tCL", "tRCD", "tRP") if k in candidate}
        for port in ("mem_req_port", "mem_side_ports"):
            peers = child.get(port, {}).get("peer", [])
            if isinstance(peers, str):
                peers = [peers]
            for peer in peers:
                candidates = [n for n in config if peer.startswith(n + ".")]
                if candidates:
                    pending.append(max(candidates, key=len))
    return {**node,
            "configured_read_bandwidth_Bps": c.get("metrics_read_bandwidth") or None,
            "configured_write_bandwidth_Bps": c.get("metrics_write_bandwidth") or None,
            "link_width": c.get("metrics_link_width") or None,
            "link_speed_GTps": c.get("metrics_link_speed") or None,
            "protocol_latency_ticks": c.get("proto_proc_lat"),
            "device_memory_latency": memory if node["endpoint"] else None}


class Trace:
    def __init__(self, events, config, metadata):
        self.events = events
        starts = [e for e in events if e["event"] == "start"]
        ends = [e for e in events if e["event"] == "end"]
        if len(starts) != 1 or not ends:
            raise ValueError("Expected one start and a clean end; trace may be truncated")
        self.begin, self.end = starts[0]["tick"], ends[-1]["tick"]
        self.frequency = starts[0]["tick_frequency"]
        if self.frequency <= 0 or self.end < self.begin:
            raise ValueError("Invalid simulation timebase")
        self.nodes = {e["node"]: e for e in events if e["event"] == "node"}
        fabric_configs = {e["node"]: e for e in events if e["event"] == "fabric_config"}
        self.fabric_nodes = set(fabric_configs)
        self.node_meta = {n: node_metadata(e, dict(walk_config(config)))
                          for n, e in self.nodes.items()}
        for node, e in fabric_configs.items():
            nm = self.node_meta[node]
            rate = e["width_bytes"] * self.frequency / nm["clock_period"]
            nm.update(configured_read_bandwidth_Bps=rate,
                      configured_write_bandwidth_Bps=rate,
                      bandwidth_source="modeled crossbar width / clock period",
                      width_bytes=e["width_bytes"], request_capacity=None, response_capacity=None,
                      queue_kind="upstream retry waiters; packets remain at source")
        self.endpoints = sorted(n for n, e in self.nodes.items() if e["endpoint"])
        self.links = sorted(n for n, e in self.nodes.items() if not e["endpoint"])
        self.transactions = {}
        self.queues = defaultdict(list)
        self.transfers = defaultdict(list)
        self.demand = defaultdict(list)
        self.active = defaultdict(lambda: {d: [] for d in DIRECTIONS})
        self.blocks = defaultdict(list)
        self.bandwidth_blocks = defaultdict(list)
        self.busy = defaultdict(list)
        self.wire_active = defaultdict(lambda: {d: [] for d in DIRECTIONS})
        self.full = defaultdict(list)
        self.phases = []
        pending_blocks, pending_phases = {}, {}
        for e in events:
            kind, tick = e["event"], e["tick"]
            node = e.get("node")
            if kind == "issue":
                self.transactions[e["id"]] = {**e, "events": [], "endpoint": None,
                                               "entered": {}, "left": {}}
            elif "id" in e:
                if e["id"] not in self.transactions:
                    raise ValueError("Event references an unknown transaction")
                t = self.transactions[e["id"]]
                t["events"].append(e)
                if kind == "endpoint":
                    if t["endpoint"] not in (None, node):
                        raise ValueError("Transaction changed endpoint")
                    if t["endpoint"] is None:
                        self.demand[node].append((t["tick"], t["op"], t["bytes"]))
                    t["endpoint"] = node
                elif kind == "request_enqueue":
                    t["entered"][node] = tick
                    if node not in self.endpoints:
                        self.demand[node].append((tick, t["op"], t["bytes"]))
                elif kind == "response_dequeue":
                    t["left"][node] = tick
                elif kind == "complete":
                    t["completion"] = tick
                elif kind == "unacknowledged":
                    t["unacknowledged"] = tick
                elif kind == "queue_full":
                    self.full[node].append(tick)
                if kind in ("transfer_read", "transfer_write"):
                    direction = kind.removeprefix("transfer_")
                    interval = (tick, tick + e["value"])
                    self.wire_active[node][direction].append(interval)
                    if t["endpoint"]:
                        self.wire_active[t["endpoint"]][direction].append(interval)
                if kind in ("request_enqueue", "request_dequeue",
                            "response_enqueue", "response_dequeue"):
                    delta = 1 if kind.endswith("enqueue") else -1
                    # Atomic operations occupy the read-class FIFO once.
                    rd, wr = (delta, 0) if t["op"] in ("read", "atomic") else (0, delta)
                    q = "request" if kind.startswith("request") else "response"
                    self.queues[node, q].append((tick, rd, wr))
                if kind == "request_dequeue" and t["op"] in ("write", "atomic"):
                    self.transfers[node].append((tick, "write", t["bytes"]))
                if kind == "response_dequeue" and t["op"] in ("read", "atomic"):
                    self.transfers[node].append((tick, "read", t["bytes"]))
            elif kind == "busy":
                self.busy[e.get("resource", node), e["direction"]].append((tick, e["until"]))
            elif kind == "block":
                key = node, e["channel"]
                if e["blocked"]:
                    if key in pending_blocks:
                        raise ValueError("Duplicate backpressure begin")
                    pending_blocks[key] = tick
                else:
                    if key not in pending_blocks:
                        raise ValueError("Backpressure end without begin")
                    interval = (pending_blocks.pop(key), tick)
                    self.blocks[node].append(interval)
            elif kind == "phase_begin":
                if e["name"] in pending_phases:
                    raise ValueError("A phase name cannot overlap itself")
                pending_phases[e["name"]] = tick
            elif kind == "phase_end":
                if e["name"] not in pending_phases:
                    raise ValueError("Phase end without begin")
                self.phases.append((e["name"], pending_phases.pop(e["name"]), tick, True))
        for (node, channel), start in pending_blocks.items():
            self.blocks[node].append((start, self.end))
        for name, start in pending_phases.items():
            self.phases.append((name, start, self.end, False))
        for t in self.transactions.values():
            for node, start in t["entered"].items():
                stop = t["left"].get(node, t.get("unacknowledged", self.end))
                for d in DIRECTIONS:
                    if t["op"] in (d, "atomic"):
                        self.active[node][d].append((start, stop))
        # Attribute modeled transport activity to the endpoint and bridge
        # traversed by each transaction, without inventing serialization delays.
        self.transport_nodes = set(self.fabric_nodes)
        for t in self.transactions.values():
            transfer_events = [e for e in t["events"] if e["event"] in ("transfer_read", "transfer_write")]
            if transfer_events:
                destinations = set(t["entered"]) - self.fabric_nodes
                if t["endpoint"]:
                    destinations.add(t["endpoint"])
                self.transport_nodes.update(destinations)
                for n in destinations:
                    for e in transfer_events:
                        self.wire_active[n][e["event"].removeprefix("transfer_")].append((e["tick"], e["tick"] + e["value"]))
        # Bandwidth stalls are only the intersection of actual serialization
        # occupancy with requests waiting for a crossbar arbitration port.
        waiting = defaultdict(list)
        for t in self.transactions.values():
            for n in set(t["entered"]) & self.fabric_nodes:
                for direction in ("request", "response"):
                    starts = [e["tick"] for e in t["events"] if e["node"] == n and e["event"] == direction + "_enqueue"]
                    stops = [e["tick"] for e in t["events"] if e["node"] == n and e["event"] == direction + "_dequeue"]
                    if starts:
                        resource = n
                        if direction == "response":
                            destinations = [e["value"] for e in t["events"] if e["node"] == n and e["event"] == "response_resource"]
                            if destinations:
                                resource = n.rsplit(".port.", 1)[0] + ".response." + str(destinations[0])
                        waiting[n, resource, direction].append((min(starts), min(stops) if stops else self.end))
        for (node, resource, direction), intervals in waiting.items():
            self.bandwidth_blocks[node].extend(intersection(intervals, self.busy[resource, direction]))
        self.metadata = {**metadata, "simulation_tick_frequency": self.frequency,
                         "endpoint_count": len(self.endpoints),
                         "topology": {},
                         "endpoints": {str(i): self.node_meta[n]
                                       for i, n in enumerate(self.endpoints)},
                         "links": {str(i): self.node_meta[n]
                                   for i, n in enumerate(self.links)}}
        # Keep port connections to disambiguate multihop fabrics and shared links.
        self.metadata["topology"] = {
            n: {k: v for k, v in c.items() if isinstance(v, dict) and "peer" in v}
            for n, c in walk_config(config) if n in self.nodes or any(port.startswith(n + ".port.") for port in self.fabric_nodes)}
        self.metadata.update(
            endpoint_capacity={n: self.node_meta[n]["capacity_bytes"] for n in self.endpoints},
            link_width_and_speed={n: {k: self.node_meta[n][k] for k in ("link_width", "link_speed_GTps")} for n in self.nodes},
            configured_read_bandwidth={n: self.node_meta[n]["configured_read_bandwidth_Bps"] for n in self.nodes},
            configured_write_bandwidth={n: self.node_meta[n]["configured_write_bandwidth_Bps"] for n in self.nodes},
            device_memory_latency={n: self.node_meta[n]["device_memory_latency"] for n in self.endpoints},
            queue_capacities={n: {k: self.node_meta[n][k] for k in ("request_capacity", "response_capacity")} for n in self.nodes})
        self.metadata["definitions"] = {
            "bytes": "CXL.mem payload bytes; atomic transfers count in both directions",
            "latency": "first host-facing CXL timing attempt to successful host response",
            "device_service": "backend acceptance to backend response; includes backend internal scheduling",
            "activity": "union of observed payload-bearing crossbar serialization intervals; null without a modeled transport",
            "queue": "request and response FIFOs reported separately; atomic occupies read-class queue once",
            "cycles": "blocked ticks divided by each node clock period; global cycles unavailable for mixed clocks",
            "phase": "issue counters and transfer events in [begin,end); latencies of completions in [begin,end)",
            "utilization": "payload bytes / elapsed seconds / configured directional payload capacity",
            "oversubscription": "host-issued endpoint demand (port-arrival demand for links) exceeding configured window capacity; not proof of modeled throttling",
            "bandwidth_stall_cycles": "actual crossbar serialization occupancy intersected with CXL arbitration waiting; FIFO-only nodes expose generic backpressure",
        }

    def report(self, begin, end, window_ticks, phase="run", include_end=False):
        if window_ticks <= 0:
            raise ValueError("Window length must be positive")
        elapsed = end - begin
        seconds = elapsed / self.frequency
        # Include events at run exit in counters; intervals have zero length there.
        def inside(tick):
            return begin <= tick < end or (include_end and tick == end)
        result, windows = {}, {}
        scopes = [("cxl", self.endpoints)]
        scopes += [(f"cxl.endpoint.{i}", [n]) for i, n in enumerate(self.endpoints)]
        scopes += [(f"cxl.link.{i}", [n]) for i, n in enumerate(self.links)]
        endpoint_bandwidths, endpoint_requests = [], []
        for prefix, nodes in scopes:
            global_scope = prefix == "cxl"
            transactions = [t for t in self.transactions.values()
                            if global_scope or t["endpoint"] in nodes
                            or (prefix.startswith("cxl.link") and any(n in t["entered"] for n in nodes))]
            selected = [t for t in transactions if inside(t["tick"])]
            counts = Counter(t["op"] for t in selected)
            m = {f"{d}_requests": counts[d] for d in (*DIRECTIONS, "atomic")}
            m["total_requests"] = len(selected)
            m["incomplete_requests"] = sum(t.get("completion", t.get("unacknowledged", end + 1)) > end
                                            for t in transactions if t["tick"] <= end)
            # Global bytes count endpoint boundaries once, never every fabric hop.
            traffic = sorted(x for n in nodes for x in self.transfers[n] if inside(x[0]))
            totals = Counter()
            for _, direction, size in traffic:
                totals[direction] += size
            for d in DIRECTIONS:
                m[f"{d}_bytes"] = totals[d]
                m[f"{d}_bandwidth_GBps"] = totals[d] / seconds / 1e9 if seconds else 0.0
            m["total_bytes"] = sum(totals.values())
            m["combined_bandwidth_GBps"] = sum(m[f"{d}_bandwidth_GBps"] for d in DIRECTIONS)
            rw = counts["read"] + counts["write"]
            for d in DIRECTIONS:
                m[f"{d}_ratio"] = counts[d] / rw if rw else 0.0
            completed = [t for t in transactions if "completion" in t and inside(t["completion"])]
            for d in DIRECTIONS:
                m[f"{d}_latency_ticks"] = distribution(Counter(
                    t["completion"] - t["tick"] for t in completed if t["op"] == d))
            components = defaultdict(Counter)
            for t in completed:
                stamps = {k: min((e["tick"] for e in t["events"] if e["event"] == k), default=None)
                          for k in ("request_enqueue", "service_start", "service_complete")}
                device_enqueues = [e["tick"] for e in t["events"]
                                   if e["event"] == "request_enqueue" and e["node"] == t["endpoint"]]
                if not device_enqueues or None in stamps.values():
                    continue
                issue, fabric, dev, start, done, finish = (t["tick"], stamps["request_enqueue"],
                    min(device_enqueues), stamps["service_start"], stamps["service_complete"], t["completion"])
                if not issue <= fabric <= dev <= start <= done <= finish:
                    raise ValueError("Non-monotonic request timestamps")
                # Queue includes pre-admission host wait; fabric includes transport
                # and intermediate switch residence. These telescope exactly.
                values = {"fabric": dev - fabric, "queue": fabric - issue + start - dev,
                          "device": done - start, "return_path": finish - done,
                          "total": finish - issue}
                for key, value in values.items():
                    components[key][value] += 1
            for key in ("fabric", "queue", "device", "return_path", "total"):
                m[f"latency.{key}"] = distribution(components[key])
            capacity = {}
            for d in DIRECTIONS:
                rates = [self.node_meta[n][f"configured_{d}_bandwidth_Bps"] for n in nodes]
                if any(x is not None and (not math.isfinite(x) or x <= 0) for x in rates):
                    raise ValueError("Configured bandwidth must be finite and positive")
                capacity[d] = sum(rates) if rates and all(x is not None for x in rates) else None
                m[f"{d}_utilization"] = totals[d] / seconds / capacity[d] if seconds and capacity[d] else None
            combined_capacity = sum(capacity.values()) if all(capacity.values()) else None
            m["combined_utilization"] = m["total_bytes"] / seconds / combined_capacity if seconds and combined_capacity else None
            # Window edges stay aligned with simulation tick zero, including phases.
            bins = []
            cursor = begin
            while cursor < end:
                stop = min(end, (cursor // window_ticks + 1) * window_ticks)
                bins.append({"begin_tick": cursor, "end_tick": stop,
                             "cxl.window.read_bytes": 0, "cxl.window.write_bytes": 0,
                             "demand_read_bytes": 0, "demand_write_bytes": 0})
                cursor = stop
            def bin_index(tick):
                return min(len(bins) - 1, tick // window_ticks - begin // window_ticks)
            for tick, d, size in traffic:
                if bins:
                    bins[bin_index(tick)][f"cxl.window.{d}_bytes"] += size
            for n in nodes:
                for tick, d, size in self.demand[n]:
                    if inside(tick) and bins:
                        for direction in DIRECTIONS:
                            if d in (direction, "atomic"):
                                bins[bin_index(tick)][f"demand_{direction}_bytes"] += size
            oversubscribed_ticks = excess = oversubscribed = 0
            peaks = Counter()
            for b in bins:
                dt = b["end_tick"] - b["begin_tick"]
                sec = dt / self.frequency
                over = False
                for d in DIRECTIONS:
                    bw = b[f"cxl.window.{d}_bytes"] / sec / 1e9
                    b[f"cxl.{d}_bandwidth_GBps"] = bw
                    peaks[d] = max(peaks[d], bw)
                    if capacity[d]:
                        extra = max(0, b[f"demand_{d}_bytes"] - capacity[d] * sec)
                        excess += extra
                        over |= extra > 0
                combined = sum(b[f"cxl.{d}_bandwidth_GBps"] for d in DIRECTIONS)
                b["cxl.combined_bandwidth_GBps"] = combined
                peaks["combined"] = max(peaks["combined"], combined)
                b["oversubscribed"] = over if all(capacity.values()) else None
                if over:
                    oversubscribed += 1
                    oversubscribed_ticks += dt
            for d in (*DIRECTIONS, "combined"):
                m[f"peak_{d}_bandwidth_GBps"] = peaks[d]
            m.update(oversubscribed_windows=oversubscribed if all(capacity.values()) else None,
                     oversubscribed_time_fraction=oversubscribed_ticks / elapsed if elapsed and all(capacity.values()) else None,
                     excess_demand_bytes=excess if all(capacity.values()) else None)
            windows[prefix] = bins
            activity = {d: [x for n in nodes for x in self.wire_active[n][d]] for d in DIRECTIONS}
            activity_available = any(n in self.transport_nodes for n in nodes)
            m.update({k: v if activity_available else None for k, v in
                      behavior(activity["read"], activity["write"], begin, end).items()})
            m["queue_full_events"] = sum(inside(t) for n in nodes for t in self.full[n])
            blocked = [x for n in nodes for x in self.blocks[n]]
            m["backpressure_ticks"] = duration(clipped(blocked, begin, end))
            periods = {self.nodes[n]["clock_period"] for n in nodes}
            m["backpressure_cycles"] = m["backpressure_ticks"] / next(iter(periods)) if len(periods) == 1 else None
            bw_stalls = duration(clipped([x for n in nodes for x in self.bandwidth_blocks[n]], begin, end))
            m["bandwidth_stall_cycles"] = (bw_stalls / next(iter(periods))
                                            if len(periods) == 1 and any(n in self.fabric_nodes for n in nodes) else None)
            for queue in ("request", "response"):
                q = [x for n in nodes for x in self.queues[n, queue]]
                for d, dist in zip((*DIRECTIONS, "total"), queue_hist(q, begin, end)):
                    m[f"{queue}_queue.{d}_queue_depth"] = dist
                    if queue == "request":
                        m[f"{d}_queue_depth"] = dist
            # Explicit aliases requested by the endpoint/link metric catalogue.
            m["queue_depth"] = m["total_queue_depth"]
            m["utilization"] = m["combined_utilization"]
            for d in DIRECTIONS:
                m[f"{d}_latency"] = m[f"{d}_latency_ticks"]
                m[f"{d}_bandwidth"] = m[f"{d}_bandwidth_GBps"]
            result.update({f"{prefix}.{key}": value for key, value in m.items()})
            if prefix.startswith("cxl.endpoint"):
                endpoint_bandwidths.append(m["combined_bandwidth_GBps"])
                endpoint_requests.append(m["total_requests"])
        # Global congestion includes both transport and endpoints, using union
        # durations to avoid counting overlapping stalls multiple times.
        all_nodes = list(self.nodes)
        result["cxl.queue_full_events"] = sum(inside(t) for n in all_nodes for t in self.full[n])
        blocked_ticks = duration(clipped([x for n in all_nodes for x in self.blocks[n]], begin, end))
        result["cxl.backpressure_ticks"] = blocked_ticks
        periods = {e["clock_period"] for e in self.nodes.values()}
        result["cxl.backpressure_cycles"] = blocked_ticks / next(iter(periods)) if len(periods) == 1 else None
        fabric_periods = {self.nodes[n]["clock_period"] for n in self.fabric_nodes}
        bw_stalls = duration(clipped([x for n in self.fabric_nodes for x in self.bandwidth_blocks[n]], begin, end))
        result["cxl.bandwidth_stall_cycles"] = bw_stalls / next(iter(fabric_periods)) if len(fabric_periods) == 1 else None
        # Aggregate host queues from each transaction's outermost CXL boundary.
        hosts = {t["node"] for t in self.transactions.values()}
        for label, nodes in (("host", hosts), ("switch_port", set(self.links) - hosts),
                             ("device", set(self.endpoints))):
            for d, dist in zip((*DIRECTIONS, "total"), queue_hist(
                    [x for n in nodes for x in self.queues[n, "request"]], begin, end)):
                result[f"cxl.{label}.{d}_queue_depth"] = dist
        mean = sum(endpoint_bandwidths) / len(endpoint_bandwidths) if endpoint_bandwidths else 0
        variance = sum((x - mean)**2 for x in endpoint_bandwidths) / len(endpoint_bandwidths) if endpoint_bandwidths else 0
        result["cxl.endpoint_bandwidth_cv"] = math.sqrt(variance) / mean if mean else 0.0
        result["cxl.endpoint_busiest_to_average"] = max(endpoint_bandwidths) / mean if mean else 0.0
        avg_requests = sum(endpoint_requests) / len(endpoint_requests) if endpoint_requests else 0
        result["cxl.endpoint_request_imbalance"] = max(endpoint_requests) / avg_requests if avg_requests else 0.0
        return {"metadata": {**self.metadata, "phase": phase, "begin_tick": begin,
                             "end_tick": end, "window_ticks": window_ticks},
                "metrics": result, "windows": windows}

    def reports(self, window_ticks):
        report = self.report(self.begin, self.end, window_ticks, include_end=True)
        report["phases"] = []
        for name, begin, end, complete in self.phases:
            phase = self.report(begin, end, window_ticks, name)
            phase["metadata"]["complete"] = complete
            report["phases"].append(phase)
        return report


def read_report(trace, config, metadata, output, window_ticks):
    print('Loading CXL trace: ' + str(trace), flush=True)
    with open(trace) as f:
        events = [json.loads(line) for line in f if line.strip()]
    with open(config) as f:
        config = json.load(f)
    with open(metadata) as f:
        metadata = json.load(f)
    required = ("run_id", "workload", "placement_policy", "cxl_version", "random_seed", "commit_sha")
    if any(k not in metadata for k in required):
        raise ValueError(f"Metadata requires {', '.join(required)}")
    print('Indexing CXL events: ' + str(len(events)), flush=True)
    indexed = Trace(events, config, metadata)
    print('Computing CXL reports', flush=True)
    report = indexed.reports(window_ticks)
    Path(output).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def run_sample(command, seconds):
    """Take periodic gem5 snapshots and gracefully finish an incomplete trial."""
    started = time.monotonic()
    with subprocess.Popen(command) as process:
        sampled = False
        while process.poll() is None:
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                sampled = True
                print('Trial interval reached; requesting gem5 exit and final statistics', flush=True)
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                break
            try:
                process.wait(timeout=min(300, remaining))
            except subprocess.TimeoutExpired:
                if time.monotonic() - started < seconds:
                    try:
                        process.send_signal(signal.SIGUSR1)
                    except ProcessLookupError:
                        pass
                    print('Requested intermediate gem5 statistics snapshot', flush=True)
        return process.returncode, sampled, time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="derive metrics from a completed simulator trace")
    for flag in ("trace", "config", "metadata", "output"):
        report.add_argument("--" + flag, required=True)
    report.add_argument("--window-ticks", type=int, default=1_000_000_000)
    run = sub.add_parser("run", help="run gem5 with CXL collection and write cxl-metrics.json")
    run.add_argument("--output-dir", required=True)
    run.add_argument("--workload", required=True)
    run.add_argument("--placement-policy", required=True)
    run.add_argument("--cxl-version", required=True)
    run.add_argument("--random-seed", type=int, default=5489)
    run.add_argument('--workload-size', choices=['full', 'smoke'], default='full')
    run.add_argument('--trial-seconds', type=float)
    run.add_argument("--window-ticks", type=int, default=1_000_000_000)
    run.add_argument("simulator", nargs=argparse.REMAINDER,
                     help="-- path/to/gem5.opt config.py [configuration arguments]")
    args = parser.parse_args()
    if args.window_ticks <= 0:
        parser.error("--window-ticks must be positive")
    if args.command == "report":
        read_report(args.trace, args.config, args.metadata, args.output, args.window_ticks)
        return
    if args.trial_seconds is not None and (not math.isfinite(args.trial_seconds) or args.trial_seconds <= 0):
        parser.error('--trial-seconds must be finite and positive')
    command = args.simulator
    if command and command[0] == "--":
        command = command[1:]
    if len(command) < 2:
        parser.error("Expected gem5 binary and config script after --")
    directory = Path(args.output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "cxl-events.jsonl").exists():
        parser.error("Output directory already contains a CXL trace; choose a fresh directory")
    repo = Path(__file__).resolve().parents[1]
    metadata = {"run_id": str(uuid.uuid4()), "workload": args.workload,
                "workload_size": args.workload_size,
                "placement_policy": args.placement_policy, "cxl_version": args.cxl_version,
                "random_seed": args.random_seed,
                "commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True))}
    (directory / "cxl-run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    # The bootstrap sets the actual simulator RNG before executing the user's
    # configuration. It does not reset it between phases or simulate() calls.
    bootstrap = directory / "cxl-bootstrap.py"
    bootstrap.write_text("import _m5.core, runpy, sys\n"
                         f"_m5.core.seedRandom({args.random_seed!r})\n"
                         f"sys.argv = {command[1:]!r}\n"
                         "sys.path.insert(0, str(__import__('pathlib').Path(sys.argv[0]).resolve().parent))\n"
                         "runpy.run_path(sys.argv[0], run_name='__m5_main__')\n")
    env = dict(os.environ, SIMCXL_METRICS_TRACE=str(directory / "cxl-events.jsonl"))
    invocation = [command[0], "--outdir=" + str(directory), str(bootstrap)]
    started = time.monotonic()
    if args.trial_seconds is None:
        returncode = subprocess.run(invocation, env=env).returncode
        sampled = False
        simulation_seconds = time.monotonic() - started
    else:
        # Environment belongs to the child, just as in the ordinary run path.
        invocation = ['env', 'SIMCXL_METRICS_TRACE=' + str(directory / 'cxl-events.jsonl'), *invocation]
        returncode, sampled, simulation_seconds = run_sample(invocation, args.trial_seconds)
    trial = {'simulation_wall_seconds': simulation_seconds, 'sample_limit_seconds': args.trial_seconds,
             'incomplete_sample': sampled, 'simulator_returncode': returncode}
    (directory / 'timing.json').write_text(json.dumps(trial, indent=2) + '\n')
    if returncode and not sampled:
        raise SystemExit(returncode)
    if sampled:
        metadata.update(calibration_sample=True, sample_complete=False)
        (directory / 'cxl-run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    report_path = directory / ('cxl-metrics.partial.json' if sampled else 'cxl-metrics.json')
    report_started = time.monotonic()
    try:
        read_report(directory / "cxl-events.jsonl", directory / "config.json",
                    directory / "cxl-run.json", report_path, args.window_ticks)
    except (ValueError, OSError) as exc:
        if not sampled:
            raise
        trial['report_error'] = str(exc)
        print('Partial report unavailable; retained raw trace and gem5 stats: ' + str(exc), flush=True)
    finally:
        trial['report_wall_seconds'] = time.monotonic() - report_started
        (directory / 'timing.json').write_text(json.dumps(trial, indent=2) + '\n')
    if sampled:
        raise SystemExit(124)
    print(directory / "cxl-metrics.json")


if __name__ == "__main__":
    main()
