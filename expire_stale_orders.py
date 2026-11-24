from __future__ import annotations

import argparse
from datetime import date

from audit_pending_orders import (
    PendingOrderAuditor,
)
from database.pending_order_query import (
    PendingOrderQuery,
)
from database.storage import (
    get_default_database_path,
)
from database.trading_storage import (
    TradingStorage,
)
from trading.execution_readiness import (
    ExecutionReadinessChecker,
)
from trading.stale_order_service import (
    StaleOrderSafetyError,
    StaleOrderService,
)


def parse_date(
    value: str,
) -> date:

    try:
        return date.fromisoformat(
            value.strip()
        )

    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Date must use YYYY-MM-DD."
        ) from exc


def create_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Safely expire PENDING paper orders "
            "whose near-open execution window "
            "has already passed."
        )
    )

    parser.add_argument(
        "--session",
        type=parse_date,
        required=True,
        help=(
            "Execution session in YYYY-MM-DD format."
        ),
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Actually reject expired orders. "
            "Without this flag the command is read-only."
        ),
    )

    return parser


def build_service():

    database_path = (
        get_default_database_path()
    )

    auditor = (
        PendingOrderAuditor(
            database_path=database_path
        )
    )

    readiness_checker = (
        ExecutionReadinessChecker(
            auditor=auditor
        )
    )

    pending_order_query = (
        PendingOrderQuery(
            database_path
        )
    )

    trading_storage = (
        TradingStorage(
            database_path
        )
    )

    trading_storage.initialize()

    service = (
        StaleOrderService(
            readiness_checker=(
                readiness_checker
            ),
            pending_order_query=(
                pending_order_query
            ),
            trading_storage=(
                trading_storage
            ),
        )
    )

    return (
        service,
        readiness_checker,
    )


def print_preview(
    readiness,
) -> None:

    print()
    print(
        "Stale Order Expiration Preview"
    )
    print(
        "=============================="
    )

    print(
        f"Session: "
        f"{readiness.execution_session}"
    )

    print(
        f"Pending orders: "
        f"{readiness.pending_orders}"
    )

    print(
        f"Clean orders: "
        f"{readiness.clean_orders}"
    )

    print(
        f"Problem orders: "
        f"{readiness.problem_orders}"
    )

    print(
        f"Window closed: "
        f"{not readiness.execution_window_open}"
    )

    print(
        f"Current time: "
        f"{readiness.checked_at_et.strftime('%Y-%m-%d %I:%M:%S %p %Z')}"
    )

    print(
        f"Window closed at: "
        f"{readiness.window_close_et.strftime('%Y-%m-%d %I:%M:%S %p %Z')}"
    )

    print()

    if (
        readiness.pending_orders > 0
        and readiness.problem_orders == 0
        and readiness.checked_at_utc
        > readiness.window_close_utc
    ):

        print(
            "These orders are eligible "
            "for stale-order rejection."
        )

    else:

        print(
            "These orders are NOT eligible "
            "for stale-order rejection."
        )


def main() -> int:

    parser = create_parser()

    args = parser.parse_args()

    (
        service,
        readiness_checker,
    ) = build_service()

    readiness = (
        readiness_checker.check(
            args.session
        )
    )

    print_preview(
        readiness
    )

    if not args.confirm:

        print()
        print(
            "READ-ONLY MODE"
        )

        print(
            "No order statuses were changed."
        )

        print(
            "Run again with --confirm "
            "to perform the rejection."
        )

        return 0

    print()
    print(
        "CONFIRMED MUTATION"
    )
    print(
        "------------------"
    )

    try:

        result = (
            service.expire_session(
                args.session
            )
        )

    except StaleOrderSafetyError as exc:

        print(
            f"SAFETY BLOCK: {exc}"
        )

        return 1

    print(
        f"Orders discovered: "
        f"{result.discovered_orders}"
    )

    print(
        f"Orders rejected: "
        f"{result.rejected_orders}"
    )

    if result.rejection_code:

        print(
            f"Rejection code: "
            f"{result.rejection_code}"
        )

    if result.rejection_reason:

        print(
            f"Reason: "
            f"{result.rejection_reason}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )