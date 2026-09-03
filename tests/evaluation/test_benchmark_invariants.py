"""Benchmark Invariants Test Suite: Strategy Fairness, Order Invariance, Reproducibility & Safety."""

import json
import pytest

from benchmark.baselines import (
    BlindImmediateRetry,
    NoActionBaseline,
    RecoverXAgent,
    RuleHeuristicBaseline,
)
from benchmark.run_benchmark import run_benchmark
from benchmark.scenarios import generate_scenarios
from benchmark.simulator import PaymentEnvironmentSimulator, derive_action_seed


def test_benchmark_strategy_fairness_deterministic_outcomes():
    """Test A — Strategy fairness: For any (seed, scenario, action), outcome is perfectly deterministic."""
    scenarios = generate_scenarios(count=50, seed=42)
    sim1 = PaymentEnvironmentSimulator(seed=42)
    sim2 = PaymentEnvironmentSimulator(seed=42)

    for scen in scenarios:
        for action in ["RETRY_SAME_METHOD", "SWITCH_TO_UPI", "DELAYED_RETRY", "PAYMENT_LINK", "STOP_RECOVERY"]:
            res1 = sim1.evaluate_action(scen, action)
            res2 = sim2.evaluate_action(scen, action)

            assert res1.recovered == res2.recovered
            assert res1.recovered_amount == res2.recovered_amount
            assert res1.execution_cost == res2.execution_cost
            assert res1.friction_cost == res2.friction_cost
            assert res1.net_revenue_recovered == res2.net_revenue_recovered
            assert res1.hard_stop_violation == res2.hard_stop_violation


def test_benchmark_strategy_order_invariance():
    """Test B — Strategy-order invariance: Strategy results are 100% independent of execution order."""
    order_1 = [
        NoActionBaseline(),
        BlindImmediateRetry(),
        RuleHeuristicBaseline(),
        RecoverXAgent(),
    ]
    order_2 = [
        RecoverXAgent(),
        RuleHeuristicBaseline(),
        BlindImmediateRetry(),
        NoActionBaseline(),
    ]
    order_3 = [
        RuleHeuristicBaseline(),
        RecoverXAgent(),
        NoActionBaseline(),
        BlindImmediateRetry(),
    ]

    rep1 = run_benchmark(seed=42, num_transactions=200, verbose=False, strategies=order_1)
    rep2 = run_benchmark(seed=42, num_transactions=200, verbose=False, strategies=order_2)
    rep3 = run_benchmark(seed=42, num_transactions=200, verbose=False, strategies=order_3)

    for strat_name in [NoActionBaseline.name, BlindImmediateRetry.name, RuleHeuristicBaseline.name, RecoverXAgent.name]:
        m1 = rep1.strategies[strat_name]
        m2 = rep2.strategies[strat_name]
        m3 = rep3.strategies[strat_name]

        assert m1.recovered_count == m2.recovered_count == m3.recovered_count
        assert m1.recovery_rate_pct == m2.recovery_rate_pct == m3.recovery_rate_pct
        assert m1.recovered_volume_inr == m2.recovered_volume_inr == m3.recovered_volume_inr
        assert m1.net_revenue_recovered_inr == m2.net_revenue_recovered_inr == m3.net_revenue_recovered_inr
        assert m1.hard_stop_violations == m2.hard_stop_violations == m3.hard_stop_violations


def test_benchmark_seed_determinism():
    """Invariant: Running benchmark with the same seed must produce bit-for-bit identical results."""
    rep1 = run_benchmark(seed=1234, num_transactions=150, verbose=False)
    rep2 = run_benchmark(seed=1234, num_transactions=150, verbose=False)

    rx1 = rep1.strategies[RecoverXAgent.name]
    rx2 = rep2.strategies[RecoverXAgent.name]

    assert rx1.recovered_count == rx2.recovered_count
    assert rx1.recovered_volume_inr == rx2.recovered_volume_inr
    assert rx1.net_revenue_recovered_inr == rx2.net_revenue_recovered_inr
    assert rx1.hard_stop_violations == rx2.hard_stop_violations == 0


def test_benchmark_reproducibility_identical_json():
    """Test C — Reproducibility: Same seed + transaction count produces identical metrics and serialized JSON."""
    rep1 = run_benchmark(seed=42, num_transactions=250, verbose=False)
    rep2 = run_benchmark(seed=42, num_transactions=250, verbose=False)

    dict1 = rep1.to_dict()
    dict2 = rep2.to_dict()

    assert dict1 == dict2
    assert json.dumps(dict1, sort_keys=True) == json.dumps(dict2, sort_keys=True)


def test_benchmark_seed_sensitivity_different_results():
    """Test D — Different seeds produce different scenario environments and distinct outcomes."""
    rep_seed42 = run_benchmark(seed=42, num_transactions=300, verbose=False)
    rep_seed43 = run_benchmark(seed=43, num_transactions=300, verbose=False)

    rx42 = rep_seed42.strategies[RecoverXAgent.name]
    rx43 = rep_seed43.strategies[RecoverXAgent.name]

    # Different seeds produce different random scenarios and financial volumes
    assert rep_seed42.seed != rep_seed43.seed
    assert rx42.total_volume_inr != rx43.total_volume_inr


def test_recoverx_zero_hard_stop_violations_guarantee():
    """Invariant: RecoverX must achieve strictly ZERO hard-stop policy violations across any scenario mix."""
    report = run_benchmark(seed=777, num_transactions=300, verbose=False)
    rx = report.strategies[RecoverXAgent.name]
    blind = report.strategies[BlindImmediateRetry.name]

    assert rx.hard_stop_violations == 0
    assert blind.hard_stop_violations > 0


def test_recoverx_net_revenue_lift_over_blind_retry():
    """Invariant: RecoverX Net Expected Value optimization must yield substantial net revenue lift over Blind Retry."""
    report = run_benchmark(seed=42, num_transactions=500, verbose=False)
    rx = report.strategies[RecoverXAgent.name]
    blind = report.strategies[BlindImmediateRetry.name]

    assert rx.net_revenue_recovered_inr > blind.net_revenue_recovered_inr
    net_lift = rx.net_revenue_recovered_inr - blind.net_revenue_recovered_inr
    assert net_lift > 50000.0
