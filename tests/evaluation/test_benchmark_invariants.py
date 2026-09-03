"""Benchmark Invariants Test Suite: Determinism, Zero Hard Stop Violations, and Net Gain Optimization."""

import pytest

from benchmark.baselines import BlindImmediateRetry, RecoverXAgent
from benchmark.run_benchmark import run_benchmark


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


def test_recoverx_zero_hard_stop_violations_guarantee():
    """Invariant: RecoverX must achieve strictly ZERO hard-stop policy violations across any scenario mix."""
    report = run_benchmark(seed=777, num_transactions=300, verbose=False)
    rx = report.strategies[RecoverXAgent.name]
    blind = report.strategies[BlindImmediateRetry.name]

    # RecoverX strictly blocks hard failures
    assert rx.hard_stop_violations == 0

    # Blind retry naively retries everything, producing violations
    assert blind.hard_stop_violations > 0


def test_recoverx_net_revenue_lift_over_blind_retry():
    """Invariant: RecoverX Net Expected Value optimization must yield substantial net revenue lift over Blind Retry."""
    report = run_benchmark(seed=42, num_transactions=500, verbose=False)
    rx = report.strategies[RecoverXAgent.name]
    blind = report.strategies[BlindImmediateRetry.name]

    assert rx.net_revenue_recovered_inr > blind.net_revenue_recovered_inr
    net_lift = rx.net_revenue_recovered_inr - blind.net_revenue_recovered_inr
    assert net_lift > 50000.0  # Demonstrates massive financial lift from avoiding wasted fees and fraud penalties
