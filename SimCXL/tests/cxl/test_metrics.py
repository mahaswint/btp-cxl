"""Analytical tests for CXL reporting, independent of the simulator binary."""
import importlib.util
from pathlib import Path
import unittest
import random

spec = importlib.util.spec_from_file_location("cxl_metrics", Path(__file__).parents[2] / "util/cxl_metrics.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class IntervalRegressionTest(unittest.TestCase):
    def test_intersection_matches_per_request_clipping(self):
        rng = random.Random(9)
        for _ in range(100):
            waiting = [(x, x + rng.randrange(20)) for x in (rng.randrange(100) for _ in range(20))]
            busy = [(x, x + rng.randrange(20)) for x in (rng.randrange(100) for _ in range(30))]
            old = [part for begin, end in waiting for part in m.clipped(busy, begin, end)]
            self.assertEqual(m.union(m.intersection(waiting, busy)), m.union(old))


def fixture():
    events = [{"event": "start", "tick": 0, "tick_frequency": 1000}]
    for node, endpoint in (("host", False), ("ep0", True), ("ep1", True)):
        events.append(dict(event="node", tick=0, node=node, endpoint=endpoint,
                           clock_period=2, request_capacity=4, response_capacity=4, capacity_bytes=1024))
    def event(kind, tick, id=None, node="host", **kw):
        e = dict(event=kind, tick=tick, **kw)
        if id is not None:
            e.update(id=id, node=node)
        events.append(e)
    event("phase_begin", 10, name="prefill")
    # One read crosses the phase begin and ends in prefill. Another write is
    # issued in prefill and completes after it. Latency belongs to completion.
    for id, op, issue, ep, fabric, dev, start, done, finish in (
            (1, "read", 5, "ep0", 8, 12, 20, 40, 50),
            (2, "write", 15, "ep1", 15, 20, 25, 35, 60)):
        event("issue", issue, id, op=op, bytes=100, response=True)
        event("endpoint", issue, id, node=ep)
        event("request_enqueue", fabric, id)
        event("request_dequeue", dev, id)
        event("request_enqueue", dev, id, node=ep)
        event("request_dequeue", start, id, node=ep)
        event("service_start", start, id, node=ep)
        event("service_complete", done, id, node=ep)
        event("response_enqueue", done, id, node=ep)
        event("response_dequeue", done+1, id, node=ep)
        event("response_enqueue", done+1, id)
        event("response_dequeue", finish, id)
        event("complete", finish, id)
    event("phase_end", 55, name="prefill")
    event("block", 22, node="ep0", channel="request", blocked=True)
    events[-1]["node"] = "ep0"
    event("block", 32, node="ep0", channel="request", blocked=False)
    events[-1]["node"] = "ep0"
    event("end", 100)
    events.sort(key=lambda x: x["tick"])
    config = {n: dict(path=n, type="CXLMemCtrl", metrics_read_bandwidth=1000,
                     metrics_write_bandwidth=1000) for n in ("host", "ep0", "ep1")}
    metadata = dict(run_id="test", workload="analytical", placement_policy="fixed",
                    cxl_version="test", random_seed=1, commit_sha="test")
    return events, config, metadata


class MetricsTest(unittest.TestCase):
    def test_weighted_quantiles_and_idle(self):
        read, write, total = m.queue_hist([(10, 1, 0), (20, 0, 1), (30, -1, 0), (40, 0, -1)], 0, 100)
        self.assertEqual(total["mean"], .4)
        self.assertEqual(total["p50"], 0)
        self.assertEqual(total["p95"], 2)
        self.assertEqual(total["count"], 100)
        self.assertEqual(read["mean"], .2)
        self.assertEqual(write["mean"], .2)
        phase = m.queue_hist([(0, 2, 0), (15, -2, 0)], 10, 20)[2]
        self.assertEqual(phase["mean"], 1)
        self.assertEqual(phase["max"], 2)

    def test_phase_deltas_latency_and_attribution(self):
        trace = m.Trace(*fixture())
        report = trace.reports(25)
        r = report["metrics"]
        self.assertEqual(r["cxl.total_requests"], 2)
        self.assertEqual(r["cxl.total_bytes"], 200)
        self.assertEqual(r["cxl.read_latency_ticks"]["p99"], 45)
        self.assertEqual(r["cxl.write_latency_ticks"]["p95"], 45)
        parts = sum(r[f"cxl.latency.{p}"]["mean"] for p in ("fabric", "queue", "device", "return_path"))
        self.assertEqual(parts, r["cxl.latency.total"]["mean"])
        self.assertEqual(r["cxl.endpoint.0.read_requests"], 1)
        self.assertEqual(r["cxl.endpoint.1.write_requests"], 1)
        self.assertEqual(r["cxl.backpressure_cycles"], 5)
        self.assertEqual(r["cxl.endpoint_bandwidth_cv"], 0)
        phase = report["phases"][0]["metrics"]
        self.assertEqual(phase["cxl.total_requests"], 1)
        self.assertEqual(phase["cxl.read_latency_ticks"]["count"], 1)
        self.assertEqual(phase["cxl.write_latency_ticks"]["count"], 0)
        self.assertEqual(sum(b["cxl.window.read_bytes"] for b in report["windows"]["cxl"]), 100)
        self.assertAlmostEqual(r["cxl.combined_bandwidth_GBps"], 2e-6)
        self.assertEqual(r["cxl.combined_utilization"], .5)

    def test_overlap_uses_interval_union(self):
        result = m.behavior([(0, 20), (10, 30)], [(10, 40)], 0, 100)
        self.assertEqual(result, dict(read_only_time=10, write_only_time=10,
            bidirectional_time=20, idle_time=60, bidirectional_overlap=.5))

    def test_missing_capacity_is_unavailable(self):
        events, config, metadata = fixture()
        config["ep1"].pop("metrics_read_bandwidth")
        report = m.Trace(events, config, metadata).reports(25)["metrics"]
        self.assertIsNone(report["cxl.read_utilization"])
        self.assertIsNone(report["cxl.oversubscribed_windows"])

    def test_unfinished_and_malformed_phases(self):
        events, config, metadata = fixture()
        events = [e for e in events if e["event"] != "phase_end"]
        report = m.Trace(events, config, metadata).reports(25)
        self.assertFalse(report["phases"][0]["metadata"]["complete"])
        with self.assertRaises(ValueError):
            m.Trace(events[:-1], config, metadata)

    def test_atomic_is_exclusive_request_class_with_two_payload_directions(self):
        events, config, metadata = fixture()
        for e in events:
            if e["event"] == "issue" and e["id"] == 1:
                e["op"] = "atomic"
        r = m.Trace(events, config, metadata).reports(25)["metrics"]
        self.assertEqual(r["cxl.atomic_requests"], 1)
        self.assertEqual(r["cxl.read_requests"], 0)
        self.assertEqual(r["cxl.total_requests"], 2)
        self.assertEqual(r["cxl.read_bytes"], 100)
        self.assertEqual(r["cxl.write_bytes"], 200)
        self.assertEqual(r["cxl.read_latency_ticks"]["count"], 0)

    def test_duplicate_endpoint_attempts_do_not_duplicate_requests(self):
        events, config, metadata = fixture()
        events.append(dict(event="endpoint", tick=6, id=1, node="ep0"))
        events.sort(key=lambda e: e["tick"])
        trace = m.Trace(events, config, metadata)
        self.assertEqual(len(trace.demand["ep0"]), 1)
        self.assertEqual(trace.reports(25)["metrics"]["cxl.total_requests"], 2)

    def test_capacity_excess_and_partial_windows(self):
        trace = m.Trace(*fixture())
        r = trace.reports(25)["metrics"]
        self.assertEqual(r["cxl.oversubscribed_windows"], 1)
        self.assertEqual(r["cxl.excess_demand_bytes"], 100)
        self.assertEqual(r["cxl.oversubscribed_time_fraction"], .25)
        phase = trace.report(10, 55, 25, "test")
        self.assertEqual([(w["begin_tick"], w["end_tick"]) for w in phase["windows"]["cxl"]], [(10, 25), (25, 50), (50, 55)])
        self.assertEqual(phase["metrics"]["cxl.incomplete_requests"], 1)

    def test_bandwidth_stall_excludes_downstream_wait(self):
        events, config, metadata = fixture()
        events.extend([dict(event="fabric_config", node="host", tick=0, width_bytes=8),
                       dict(event="busy", node="host", direction="request", tick=9, until=10),
                       dict(event="busy", node="host", direction="request", tick=10, until=11)])
        events.sort(key=lambda e: e["tick"])
        r = m.Trace(events, config, metadata).reports(25)["metrics"]
        # Read waits [8,12), but the port actually serializes only [9,11).
        self.assertEqual(r["cxl.bandwidth_stall_cycles"], 1)

    def test_reject_non_monotonic_lifecycle(self):
        events, config, metadata = fixture()
        for e in events:
            if e["event"] == "service_start" and e["id"] == 1:
                e["tick"] = 41
        events.sort(key=lambda e: e["tick"])
        with self.assertRaises(ValueError):
            m.Trace(events, config, metadata).reports(25)

    def test_exact_quantiles_and_zero_duration(self):
        self.assertEqual(m.distribution({1: 94, 100: 5, 1000: 1})["p95"], 100)
        self.assertEqual(m.distribution({1: 94, 100: 5, 1000: 1})["p99"], 100)
        report = m.Trace(*fixture()).report(10, 10, 25)
        self.assertEqual(report["metrics"]["cxl.combined_bandwidth_GBps"], 0)
        self.assertEqual(report["windows"]["cxl"], [])


if __name__ == "__main__":
    unittest.main()
