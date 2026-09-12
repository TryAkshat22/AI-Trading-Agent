from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from database.execution_attempt_storage import (
    ExecutionAttemptStorage,
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


@dataclass(frozen=True)
class PendingOrderAuditRecord:
    order_id: str
    ticker: str
    side: str
    quantity: int
    status: str
    execution_session: date
    model_version: str | None
    decision_run_id: str | None
    fill_count: int
    execution_attempt_count: int

    @property
    def clean_for_execution(self) -> bool:
        return (
            self.status == "PENDING"
            and self.fill_count == 0
            and self.execution_attempt_count == 0
            and self.decision_run_id is not None
        )


@dataclass(frozen=True)
class PendingOrderAuditResult:
    execution_session: date
    records: tuple[
        PendingOrderAuditRecord,
        ...,
    ]

    @property
    def total_orders(self) -> int:
        return len(
            self.records
        )

    @property
    def clean_orders(self) -> int:
        return sum(
            record.clean_for_execution
            for record in self.records
        )

    @property
    def problem_orders(
        self,
    ) -> tuple[
        PendingOrderAuditRecord,
        ...,
    ]:
        return tuple(
            record
            for record in self.records
            if not record.clean_for_execution
        )


class PendingOrderAuditor:
    """
    Read-only audit of persisted PENDING orders.

    This class does NOT:
        - fetch market data
        - create orders
        - execute orders
        - modify statuses
        - write fills
        - create execution attempts
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:

        if database_path is None:
            database_path = (
                get_default_database_path()
            )

        self.trading_storage = (
            TradingStorage(
                database_path
            )
        )

        self.execution_attempt_storage = (
            ExecutionAttemptStorage(
                database_path
            )
        )

        self.pending_order_query = (
            PendingOrderQuery(
                database_path
            )
        )

        # Safe schema initialization only.
        self.trading_storage.initialize()
        self.execution_attempt_storage.initialize()

    def audit_session(
        self,
        execution_session: date,
    ) -> PendingOrderAuditResult:

        pending_refs = (
            self.pending_order_query
            .find_for_session(
                execution_session
            )
        )

        fills = (
            self.trading_storage
            .list_fills()
        )

        fill_counts: dict[
            str,
            int,
        ] = {}

        for fill in fills:
            fill_counts[
                fill.order_id
            ] = (
                fill_counts.get(
                    fill.order_id,
                    0,
                )
                + 1
            )

        records: list[
            PendingOrderAuditRecord
        ] = []

        for reference in pending_refs:

            stored_order = (
                self.trading_storage
                .get_order(
                    reference.order_id
                )
            )

            if stored_order is None:
                continue

            attempts = (
                self.execution_attempt_storage
                .list_attempts_for_order(
                    reference.order_id
                )
            )

            records.append(
                PendingOrderAuditRecord(
                    order_id=(
                        stored_order.order_id
                    ),
                    ticker=(
                        stored_order.ticker
                    ),
                    side=(
                        stored_order.side
                    ),
                    quantity=(
                        stored_order.quantity
                    ),
                    status=(
                        stored_order.status
                    ),
                    execution_session=(
                        stored_order.execution_session
                    ),
                    model_version=(
                        stored_order.model_version
                    ),
                    decision_run_id=(
                        stored_order.decision_run_id
                    ),
                    fill_count=(
                        fill_counts.get(
                            stored_order.order_id,
                            0,
                        )
                    ),
                    execution_attempt_count=(
                        len(
                            attempts
                        )
                    ),
                )
            )

        return PendingOrderAuditResult(
            execution_session=(
                execution_session
            ),
            records=tuple(
                records
            ),
        )


def print_audit(
    result: PendingOrderAuditResult,
) -> None:

    print()
    print(
        "Pending Order Pre-Execution Audit"
    )

    print(
        "================================="
    )

    print(
        f"Execution session: "
        f"{result.execution_session}"
    )

    print(
        f"Orders discovered: "
        f"{result.total_orders}"
    )

    print(
        f"Clean for execution: "
        f"{result.clean_orders}"
    )

    print()

    if not result.records:

        print(
            "No PENDING orders found."
        )

        return

    for index, record in enumerate(
        result.records,
        start=1,
    ):

        print(
            f"Order {index}"
        )

        print(
            f"  Order ID: "
            f"{record.order_id}"
        )

        print(
            f"  Ticker: "
            f"{record.ticker}"
        )

        print(
            f"  Side: "
            f"{record.side}"
        )

        print(
            f"  Quantity: "
            f"{record.quantity}"
        )

        print(
            f"  Status: "
            f"{record.status}"
        )

        print(
            f"  Execution session: "
            f"{record.execution_session}"
        )

        print(
            f"  Model version: "
            f"{record.model_version}"
        )

        print(
            f"  Decision run ID: "
            f"{record.decision_run_id}"
        )

        print(
            f"  Existing fills: "
            f"{record.fill_count}"
        )

        print(
            f"  Existing execution attempts: "
            f"{record.execution_attempt_count}"
        )

        print(
            f"  Clean: "
            f"{record.clean_for_execution}"
        )

        print()

    if result.problem_orders:

        print(
            "AUDIT RESULT: ATTENTION REQUIRED"
        )

    else:

        print(
            "AUDIT RESULT: CLEAN"
        )


def main() -> None:

    target_session = date(
        2026,
        9,
        14,
    )

    auditor = (
        PendingOrderAuditor()
    )

    result = (
        auditor.audit_session(
            target_session
        )
    )

    print_audit(
        result
    )


if __name__ == "__main__":
    main()