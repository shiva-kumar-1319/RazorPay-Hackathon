"""CLI utility for running payment simulations from terminal."""

import argparse
import sys
from decimal import Decimal

from backend.app.db import SessionLocal
from backend.app.schemas.simulator import CreateSimulatedPaymentRequest, SimulateBatchRequest
from backend.app.simulator.constants import SimulationScenario
from backend.app.simulator.engine import PaymentSimulator


def main():
    parser = argparse.ArgumentParser(description="RecoverX Payment Simulator CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Single payment simulation
    single_parser = subparsers.add_parser("single", help="Simulate a single payment")
    single_parser.add_argument("--amount", type=float, help="Transaction amount in INR")
    single_parser.add_argument("--method", type=str, help="Payment method (UPI, CARD, NETBANKING, WALLET, BNPL)")
    single_parser.add_argument("--gateway", type=str, help="Gateway name (RAZORPAY, PAYU, etc.)")
    single_parser.add_argument("--outcome", type=str, choices=["SUCCESS", "FAIL"], help="Force SUCCESS or FAIL")
    single_parser.add_argument("--failure-code", type=str, help="Force specific failure code (e.g. CARD_DECLINED, OTP_TIMEOUT)")
    single_parser.add_argument("--scenario", type=str, default="NORMAL_BALANCED", help="Simulation scenario preset")
    single_parser.add_argument("--merchant", type=str, help="Merchant ID")

    # Seed customer personas
    seed_parser = subparsers.add_parser("seed-customers", help="Seed multi-transaction customer intelligence personas")
    seed_parser.add_argument("--merchant", type=str, default="merch_101", help="Merchant ID")

    # Inspect customer intelligence
    inspect_parser = subparsers.add_parser("inspect-customer", help="Inspect customer payment behavior and intelligence")
    inspect_parser.add_argument("--customer-id", type=str, required=True, help="External customer ID (e.g. cust_vip_priya)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    from backend.app.db import SessionLocal, initialize_database
    initialize_database()
    session = SessionLocal()
    simulator = PaymentSimulator(session)

    try:
        if args.command == "seed-customers":
            res = simulator.seed_customer_personas(merchant_id=args.merchant)
            print("\n=== Seed Customer Personas Result ===")
            print(f"Status:               {res['message']}")
            print(f"Customers Seeded:     {res['seeded_customers']}")
            print(f"Transactions Created: {res['seeded_transactions']}")
            print(f"Attempts Recorded:    {res['seeded_attempts']}")
            print("\nPersonas:")
            for name in res["personas"]:
                print(f"  - {name}")

        elif args.command == "inspect-customer":
            from backend.app.models.recovery import Customer
            from backend.app.services.customer_intelligence import get_customer_payment_behavior, get_customer_detail
            from sqlalchemy import select

            cust = session.scalar(
                select(Customer).where(Customer.external_customer_id == args.customer_id)
            )
            if not cust:
                print(f"Customer with external ID '{args.customer_id}' not found.")
                return

            detail = get_customer_detail(session, cust.id)
            behavior = get_customer_payment_behavior(session, cust.id)
            intel = detail.intelligence

            print(f"\n=== Customer Intelligence: {detail.name or detail.external_customer_id} ===")
            print(f"External Customer ID:    {detail.external_customer_id}")
            print(f"Merchant ID:             {detail.merchant_id}")
            print(f"Risk Tier / Segment:     {detail.risk_segment} / {intel.behavioral_segment}")
            print(f"Preferred Method:        {intel.preferred_payment_method}")
            print(f"Lifetime GMV (Spent):    INR {intel.total_spent:,.2f} ({intel.total_transactions} txns)")
            print(f"Success Rate:            {float(intel.success_rate) * 100:.1f}%")
            print(f"Recovery Yield:          {float(intel.recovery_rate) * 100:.1f}% (INR {intel.total_recovered_amount:,.2f})")
            print(f"Risk Score:              {intel.risk_score}")
            print(f"Retry Tolerance:         {behavior.retry_tolerance_score * 100:.0f}%")
            print("\nPayment Method Breakdown:")
            for m in behavior.methods:
                print(f"  - {m.method:12s}: {m.successful_attempts}/{m.total_attempts} successful ({m.success_rate * 100:.1f}%) | INR {m.total_volume:,.2f}")

        elif args.command == "single":
            scenario_enum = SimulationScenario(args.scenario)
            req = CreateSimulatedPaymentRequest(
                amount=Decimal(str(args.amount)) if args.amount else None,
                payment_method=args.method,
                gateway=args.gateway,
                target_outcome=args.outcome,
                target_failure_code=args.failure_code,
                scenario=scenario_enum,
                merchant_id=args.merchant,
            )
            res = simulator.simulate_payment(req)
            print("\n=== Single Payment Simulation Result ===")
            print(f"Transaction ID:  {res.transaction_id}")
            print(f"External Txn ID: {res.external_transaction_id}")
            print(f"Amount:          INR {res.amount} {res.currency}")
            print(f"Method / Gateway:{res.payment_method} via {res.gateway}")
            print(f"Outcome:         {res.outcome} (Status: {res.status})")
            if res.outcome == "FAIL":
                print(f"Failure Code:    {res.failure_code}")
                print(f"Category:        {res.failure_category} (Recoverable: {res.recoverable})")
                print(f"Error Message:   {res.error_message}")
            print(f"Outbox Event ID: {res.outbox_event_id}")

        elif args.command == "batch":
            scenario_enum = SimulationScenario(args.scenario)
            req = SimulateBatchRequest(
                count=args.count,
                scenario=scenario_enum,
                merchant_id=args.merchant,
                success_rate_override=args.success_rate,
            )
            res = simulator.simulate_batch(req)
            print("\n=== Batch Simulation Summary ===")
            print(f"Total Transactions:   {res.total_simulated}")
            print(f"Successful:           {res.success_count} ({res.success_rate * 100:.1f}%)")
            print(f"Failed:               {res.failure_count}")
            print(f"  - Recoverable:      {res.recoverable_failure_count}")
            print(f"  - Hard Failures:    {res.hard_failure_count}")
            print(f"Total GMV Simulated:  INR {res.total_amount:,.2f}")
            print("\nFailure Code Breakdown:")
            for code, cnt in sorted(res.failure_code_breakdown.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {code:25s}: {cnt}")
            print("\nCategory Breakdown:")
            for cat, cnt in sorted(res.category_breakdown.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {cat:20s}: {cnt}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
