"""Executable Benchmark Runner for Reproducible 4-Way Comparative Evaluation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from benchmark.baselines import (
    BaseRecoveryStrategy,
    BlindImmediateRetry,
    NoActionBaseline,
    RecoverXAgent,
    RuleHeuristicBaseline,
)
from benchmark.metrics import BenchmarkEvaluationReport, compute_benchmark_metrics
from benchmark.scenarios import generate_scenarios
from benchmark.simulator import PaymentEnvironmentSimulator


def run_benchmark(
    seed: int = 42,
    num_transactions: int = 1000,
    output_path: str | None = None,
    verbose: bool = True,
    strategies: list[BaseRecoveryStrategy] | None = None,
    explain: bool = False,
) -> BenchmarkEvaluationReport:
    """Run full reproducible benchmark comparing No Action, Blind Retry, Heuristics, and RecoverX."""
    if verbose:
        print("=" * 80)
        print(" RECOVERX BENCHMARK EVALUATOR — 4-WAY COMPARATIVE RECOVERY AUDIT")
        print(f" Deterministic Seed: {seed} | Transactions Evaluated: {num_transactions}")
        print("=" * 80)

    # 1. Generate realistic scenarios with strict hidden ground truth separation
    start_gen = time.perf_counter()
    scenarios = generate_scenarios(count=num_transactions, seed=seed)
    gen_time_ms = round((time.perf_counter() - start_gen) * 1000, 2)
    if verbose:
        print(f"[+] Generated {len(scenarios)} grounded failure events in {gen_time_ms}ms")

    # 2. Instantiate simulator and strategies
    simulator = PaymentEnvironmentSimulator(seed=seed)
    if strategies is None:
        strategies = [
            NoActionBaseline(),
            BlindImmediateRetry(),
            RuleHeuristicBaseline(),
            RecoverXAgent(),
        ]

    metrics_map = {}
    raw_results_summary = {}

    for strat in strategies:
        step_results = []
        for scen in scenarios:
            action = strat.select_action(scen.observable)
            step_res = simulator.evaluate_action(scen, action)
            step_results.append(step_res)

        m = compute_benchmark_metrics(strat.name, step_results)
        metrics_map[strat.name] = m
        raw_results_summary[strat.name] = {
            "recovered": m.recovered_count,
            "net_revenue": m.net_revenue_recovered_inr,
            "violations": m.hard_stop_violations,
        }

    # 3. Compute comparative lift summary
    no_act = metrics_map.get(NoActionBaseline.name)
    blind = metrics_map.get(BlindImmediateRetry.name)
    heur = metrics_map.get(RuleHeuristicBaseline.name)
    rx = metrics_map.get(RecoverXAgent.name)

    comparative: dict[str, Any] = {}
    if rx and blind:
        rx_lift_vs_blind = round(rx.net_revenue_recovered_inr - blind.net_revenue_recovered_inr, 2)
        comparative["recoverx_net_revenue_lift_vs_blind_inr"] = rx_lift_vs_blind
        comparative["blind_retry_hard_stop_violations"] = blind.hard_stop_violations
    else:
        rx_lift_vs_blind = 0.0

    if rx and heur:
        rx_lift_vs_heur = round(rx.net_revenue_recovered_inr - heur.net_revenue_recovered_inr, 2)
        comparative["recoverx_net_revenue_lift_vs_heuristic_inr"] = rx_lift_vs_heur
        comparative["is_recoverx_optimal"] = rx.net_revenue_recovered_inr >= heur.net_revenue_recovered_inr
    else:
        rx_lift_vs_heur = 0.0

    if rx:
        comparative["recoverx_hard_stop_violations"] = rx.hard_stop_violations
        comparative["is_safety_invariant_held"] = rx.hard_stop_violations == 0

    report = BenchmarkEvaluationReport(
        seed=seed,
        total_transactions=num_transactions,
        strategies=metrics_map,
        comparative_summary=comparative,
    )

    # 4. Display Results Table
    if verbose:
        print("\n" + "-" * 88)
        header = f"{'Strategy':<30} | {'Recov %':<8} | {'Recov (INR)':<15} | {'Net Rev (INR)':<15} | {'Violations':<10}"
        print(header)
        print("-" * 88)
        for name, m in metrics_map.items():
            print(f"{name:<30} | {m.recovery_rate_pct:>7.2f}% | INR {m.recovered_volume_inr:>10,.2f} | INR {m.net_revenue_recovered_inr:>10,.2f} | {m.hard_stop_violations:>10}")
        print("-" * 88)

        print("\n[SUMMARY LIFT]")
        print(f"* RecoverX Net Revenue vs Blind Retry:     +INR {rx_lift_vs_blind:,.2f}")
        print(f"* RecoverX Net Revenue vs Rule Heuristic:  +INR {rx_lift_vs_heur:,.2f}")
        print(f"* RecoverX Hard-Stop Violations:           {rx.hard_stop_violations} (Invariant: ZERO)")
        print(f"* Blind Retry Hard-Stop Violations:        {blind.hard_stop_violations} (Policy Failures)")

        print("\n[COMPARATIVE STRATEGY ANALYSIS (vs RecoverX)]")
        for name, m in metrics_map.items():
            if name == RecoverXAgent.name:
                continue
            rate_diff = rx.recovery_rate_pct - m.recovery_rate_pct
            rev_diff = rx.net_revenue_recovered_inr - m.net_revenue_recovered_inr
            eff_pct = ((rx.cost_efficiency_ratio - m.cost_efficiency_ratio) / m.cost_efficiency_ratio * 100) if m.cost_efficiency_ratio > 0 else 0.0
            print(f"* RecoverX vs {name}: {rate_diff:+.1f}pp recovery rate, {rev_diff:+,.0f} net revenue, {eff_pct:+.1f}% cost efficiency")

        if explain:
            print("\n[RECOVERX STRATEGY TRADE-OFF RATIONALE]")
            print("RecoverX intentionally trades a small amount of raw recovery volume for lower")
            print("execution cost and zero policy violations, netting more actual revenue.")
            print("By maximizing Net Expected Value rather than raw volume, RecoverX optimizes capital efficiency.")
        print("=" * 88 + "\n")

    # 5. Persist JSON artifact if requested
    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        if verbose:
            print(f"[OK] Benchmark artifact written to: {out_file.resolve()}")

    return report



def main() -> None:
    parser = argparse.ArgumentParser(description="Run RecoverX 4-Way Benchmark Evaluation.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    parser.add_argument("--transactions", type=int, default=1000, help="Number of failure transactions (default: 1000)")
    parser.add_argument("--output", type=str, default="benchmark/results/latest.json", help="Output JSON path")
    parser.add_argument("--quiet", action="store_true", help="Suppress console stdout")
    parser.add_argument("--explain", action="store_true", help="Print plain-English rationale for strategy trade-offs")
    args = parser.parse_args()

    run_benchmark(
        seed=args.seed,
        num_transactions=args.transactions,
        output_path=args.output,
        verbose=not args.quiet,
        explain=args.explain,
    )


if __name__ == "__main__":
    main()
