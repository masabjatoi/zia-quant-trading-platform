"""
Observability Metrics Collector
===============================
Tracks in-memory performance counters, latency histograms, and signal distribution.
"""

from typing import Dict, Any, List
import time
from collections import defaultdict


class MetricsCollector:
    """Singleton collector for real-time operational stats."""
    _instance = None

    def __init__(self):
        self.signal_counts = defaultdict(int)
        self.strategy_triggers = defaultdict(int)
        self.latencies: List[float] = []
        self.errors_count = 0
        self.start_time = time.time()

    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        if cls._instance is None:
            cls._instance = MetricsCollector()
        return cls._instance

    def record_signal(self, direction: str, strength: str) -> None:
        self.signal_counts[direction] += 1
        self.signal_counts[strength] += 1

    def record_strategy_trigger(self, strategy_name: str) -> None:
        self.strategy_triggers[strategy_name] += 1

    def record_latency(self, latency_seconds: float) -> None:
        self.latencies.append(latency_seconds)
        if len(self.latencies) > 200:
            self.latencies.pop(0)

    def record_error(self) -> None:
        self.errors_count += 1

    def get_snapshot(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        avg_lat = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
        return {
            "uptime_seconds": round(uptime, 1),
            "signal_counts": dict(self.signal_counts),
            "strategy_triggers": dict(self.strategy_triggers),
            "average_latency_ms": round(avg_lat * 1000.0, 2),
            "total_errors": self.errors_count,
        }
