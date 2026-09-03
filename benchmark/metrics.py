"""Benchmark Metrics and Comparative Performance Evaluator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import statistics
from typing import Any

from benchmark.simulator import SimulationStepResult


@dataclass(frozen=True)
class StrategyMetrics:
    strategy_name: str
    total_transactions: int
    recovered_count: int
    recovery_rate_pct: float
    total_volume_inr: float
    recovered_volume_inr: float
    total_execution_cost_inr: float
    total_friction_cost_inr: float
    net_revenue_recovered_inr: float
    cost_per_recovery_inr: float
    hard_stop_violations: int
    hard_stop_violation_rate_pct: float
    mean_latency_ms: float
    p95_latency_ms: float


@dataclass(frozen=True)
class BenchmarkEvaluationReport:
    seed: int
    total_transactions: int
    strategies: dict[str, StrategyMetrics]
    comparative_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "total_transactions": self.total_transactions,
            "strategies": {name: asdict(m) for name, m in self.strategies.items()},
            "comparative_summary": self.comparative_summary,
        }


def compute_benchmark_metrics(
    strategy_name: str,
    results: list[SimulationStepResult],
) -> StrategyMetrics:
    """Aggregate simulation results into standard benchmark metrics."""
    n = len(results)
    if n == 0:
        return StrategyMetrics(
            strategy_name=strategy_name,
            total_transactions=0,
            recovered_count=0,
            recovery_rate_pct=0.0,
            total_volume_inr=0.0,
            recovered_volume_inr=0.0,
            total_execution_cost_inr=0.0,
            total_friction_cost_inr=0.0,
            net_revenue_recovered_inr=0.0,
            cost_per_recovery_inr=0.0,
            hard_stop_violations=0,
            hard_stop_violation_rate_pct=0.0,
            mean_latency_ms=0.0,
            p95_latency_ms=0.0,
        )

    recovered = sum(1 for r in results if r.recovered)
    total_vol = sum(r.amount for r in results)
    rec_vol = sum(r.recovered_amount for r in results)
    exec_cost = sum(r.execution_cost for r in results)
    fric_cost = sum(r.friction_cost for r in results)
    net_rev = sum(r.net_revenue_recovered for r in results)
    violations = sum(1 for r in results if r.hard_stop_violation)

    latencies = sorted(r.latency_ms for r in results)
    mean_lat = round(statistics.mean(latencies), 1) if latencies else 0.0
    p95_idx = int(0.95 * len(latencies))
    p95_lat = float(latencies[min(p95_idx, len(latencies) - 1)]) if latencies else 0.0

    rec_rate = round((recovered / n) * 100, 2)
    violation_rate = round((violations / n) * 100, 2)
    cost_per_rec = round(exec_cost / recovered, 2) if recovered > 0 else 0.0

    return StrategyMetrics(
        strategy_name=strategy_name,
        total_transactions=n,
        recovered_count=recovered,
        recovery_rate_pct=rec_rate,
        total_volume_inr=round(total_vol, 2),
        recovered_volume_inr=round(rec_vol, 2),
        total_execution_cost_inr=round(exec_cost, 2),
        total_friction_cost_inr=round(fric_cost, 2),
        net_revenue_recovered_inr=round(net_rev, 2),
        cost_per_recovery_inr=cost_per_rec,
        hard_stop_violations=violations,
        hard_stop_violation_rate_pct=violation_rate,
        mean_latency_ms=mean_lat,
        p95_latency_ms=p95_lat,
    )
