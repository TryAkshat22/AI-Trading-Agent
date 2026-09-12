from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text

from database.sqlite_engine import (
    create_sqlite_engine,
)
from database.storage import (
    get_default_database_path,
)
from trading.orders import (
    OrderStatus,
)


class PendingOrderQueryError(Exception):
    """
    Base exception for pending-order discovery.
    """


class InvalidPendingOrderSessionError(
    PendingOrderQueryError
):
    """
    Raised when the requested execution session
    is invalid.
    """


@dataclass(frozen=True)
class PendingOrderReference:
    """
    Lightweight reference to one persisted order
    that is due for execution.
    """

    order_id: str

    ticker: str

    execution_session: date

    model_version: str | None


class PendingOrderQuery:
    """
    Read-only discovery layer for pending orders.

    It intentionally does not modify TradingStorage.

    Query rule:

        status = PENDING
            AND
        execution_session = requested session

    This allows the execution batch to discover its
    own work instead of requiring manually supplied
    order IDs.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:

        if database_path is None:
            database_path = (
                get_default_database_path()
            )

        self.database_path = Path(
            database_path
        )

        self.engine = create_sqlite_engine(
            self.database_path
        )

    def find_for_session(
        self,
        execution_session: date,
    ) -> tuple[
        PendingOrderReference,
        ...,
    ]:
        """
        Return every PENDING order scheduled for the
        exact requested session.
        """

        if not isinstance(
            execution_session,
            date,
        ):
            raise InvalidPendingOrderSessionError(
                "execution_session must be "
                "a datetime.date."
            )

        try:

            with self.engine.connect() as connection:

                rows = connection.execute(
                    text(
                        """
                        SELECT
                            order_id,
                            ticker,
                            execution_session,
                            model_version
                        FROM paper_orders
                        WHERE status = :status
                          AND execution_session =
                              :execution_session
                        ORDER BY
                            ticker ASC,
                            order_id ASC
                        """
                    ),
                    {
                        "status": (
                            OrderStatus.PENDING.value
                        ),
                        "execution_session": (
                            execution_session
                            .isoformat()
                        ),
                    },
                ).mappings().all()

        except Exception as exc:

            raise PendingOrderQueryError(
                "Failed to discover pending orders "
                f"for {execution_session}."
            ) from exc

        return tuple(
            self._row_to_reference(
                row
            )
            for row in rows
        )

    def find_order_ids_for_session(
        self,
        execution_session: date,
    ) -> tuple[
        str,
        ...,
    ]:
        """
        Convenience method for the existing
        PendingExecutionBatchRunner.
        """

        records = self.find_for_session(
            execution_session
        )

        return tuple(
            record.order_id
            for record in records
        )

    def count_for_session(
        self,
        execution_session: date,
    ) -> int:
        """
        Count pending orders due for one session.
        """

        return len(
            self.find_for_session(
                execution_session
            )
        )

    @staticmethod
    def _row_to_reference(
        row,
    ) -> PendingOrderReference:

        raw_session = row[
            "execution_session"
        ]

        if isinstance(
            raw_session,
            date,
        ):
            execution_session = (
                raw_session
            )

        else:
            execution_session = (
                date.fromisoformat(
                    str(
                        raw_session
                    )
                )
            )

        return PendingOrderReference(
            order_id=str(
                row[
                    "order_id"
                ]
            ),
            ticker=str(
                row[
                    "ticker"
                ]
            ),
            execution_session=(
                execution_session
            ),
            model_version=(
                row[
                    "model_version"
                ]
            ),
        )