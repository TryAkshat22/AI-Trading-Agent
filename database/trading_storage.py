from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    Mapped,
    Session,
    mapped_column,
)

from database.sqlite_engine import create_sqlite_engine
from database.storage import (
    Base,
    get_default_database_path,
    utc_iso,
)
from trading.orders import (
    Fill,
    Order,
    OrderStatus,
)
from trading.portfolio import (
    Portfolio,
    money,
)


class TradingStorageError(Exception):
    """Base exception for paper-trading persistence failures."""


class DuplicateStoredOrderError(TradingStorageError):
    """Raised when an order or fill would be duplicated."""


class StoredOrderNotFoundError(TradingStorageError):
    """Raised when an expected persisted order cannot be found."""


class InvalidStoredOrderStateError(TradingStorageError):
    """Raised when an order state transition is not allowed."""


class StoredOrder(Base):
    """
    Persistent paper order.

    source_run_id is retained for backward compatibility.
    New code should use the explicit decision-lineage table.
    """

    __tablename__ = "paper_orders"

    order_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    ticker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    side: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    signal_timestamp_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )

    execution_session: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OrderStatus.PENDING.value,
    )

    # Legacy compatibility field.
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "ingestion_runs.run_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )


class StoredOrderDecisionLineage(Base):
    """
    Explicitly records which ingestion run produced
    the information used to create an order.

    This is decision-time lineage only.
    """

    __tablename__ = "order_decision_lineage"

    order_id: Mapped[str] = mapped_column(
        ForeignKey(
            "paper_orders.order_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    decision_run_id: Mapped[str] = mapped_column(
        ForeignKey(
            "ingestion_runs.run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )


class StoredOrderRejection(Base):
    """
    Persistent explanation for a PENDING -> REJECTED
    order-state transition.
    """

    __tablename__ = "order_rejections"

    order_id: Mapped[str] = mapped_column(
        ForeignKey(
            "paper_orders.order_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )

    rejection_code: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    rejection_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    rejected_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )


class StoredFill(Base):
    """
    Persistent record of one simulated execution.

    source_run_id is retained for backward compatibility.
    New code should use the explicit execution-lineage table.
    """

    __tablename__ = "paper_fills"

    fill_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    order_id: Mapped[str] = mapped_column(
        ForeignKey(
            "paper_orders.order_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
        index=True,
    )

    ticker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    side: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    execution_session: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    reference_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    fill_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    gross_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    slippage_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    # Legacy compatibility field.
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "ingestion_runs.run_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )


class StoredFillExecutionLineage(Base):
    """
    Explicitly records which ingestion run supplied
    the execution-price observation for a fill.

    This must remain separate from decision lineage.
    """

    __tablename__ = "fill_execution_lineage"

    fill_id: Mapped[str] = mapped_column(
        ForeignKey(
            "paper_fills.fill_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    execution_run_id: Mapped[str] = mapped_column(
        ForeignKey(
            "ingestion_runs.run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )


class StoredPortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    recorded_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )

    session_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    market_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    total_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    open_position_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "session_date",
            "recorded_at_utc",
            name="uq_portfolio_snapshot_time",
        ),
    )


@dataclass(frozen=True)
class PersistedOrderResult:
    order_id: str
    database_path: Path


@dataclass(frozen=True)
class PersistedFillResult:
    fill_id: str
    order_id: str
    database_path: Path


@dataclass(frozen=True)
class PersistedPortfolioSnapshotResult:
    snapshot_id: str
    database_path: Path


@dataclass(frozen=True)
class StoredFillRecord:
    fill_id: str
    order_id: str
    ticker: str
    side: str
    quantity: int
    execution_session: date
    reference_price: Decimal
    fill_price: Decimal
    fees: Decimal
    slippage_cost: Decimal
    realized_pnl: Decimal
    created_at_utc: str

    # New explicit lineage field.
    execution_run_id: str | None = None


@dataclass(frozen=True)
class StoredOrderRecord:
    order_id: str
    ticker: str
    side: str
    quantity: int
    signal_timestamp_utc: str
    execution_session: date
    status: str

    # Legacy compatibility value.
    source_run_id: str | None

    model_version: str | None

    # New explicit lineage value.
    decision_run_id: str | None = None


@dataclass(frozen=True)
class StoredOrderRejectionRecord:
    order_id: str
    rejection_code: str
    rejection_reason: str
    rejected_at_utc: str


class TradingStorage:
    """
    Persistent repository for orders, fills,
    rejections, lineage, and portfolio snapshots.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:

        if database_path is None:
            database_path = get_default_database_path()

        self.database_path = Path(
            database_path
        ).expanduser()

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.engine = create_sqlite_engine(
            self.database_path
        )

    def initialize(self) -> None:
        """
        create_all creates the two new lineage tables
        without altering existing SQLite tables.
        """

        Base.metadata.create_all(
            self.engine
        )

    @staticmethod
    def _resolve_lineage_id(
        explicit_id: str | None,
        legacy_id: str | None,
        explicit_name: str,
        legacy_name: str,
    ) -> str | None:
        """
        Support both the new explicit API and the
        old API during the transition.

        Supplying two different IDs is rejected.
        """

        if (
            explicit_id is not None
            and legacy_id is not None
            and explicit_id != legacy_id
        ):
            raise ValueError(
                f"{explicit_name} and "
                f"{legacy_name} cannot refer "
                "to different ingestion runs."
            )

        if explicit_id is not None:
            return explicit_id

        return legacy_id

    def save_order(
        self,
        order: Order,
        source_run_id: str | None = None,
        model_version: str | None = None,
        decision_run_id: str | None = None,
    ) -> PersistedOrderResult:
        """
        Persist a new PENDING order.

        Preferred new argument:
            decision_run_id

        Legacy argument still supported:
            source_run_id
        """

        resolved_decision_run_id = (
            self._resolve_lineage_id(
                explicit_id=decision_run_id,
                legacy_id=source_run_id,
                explicit_name="decision_run_id",
                legacy_name="source_run_id",
            )
        )

        # Preserve the existing duplicate-order API.
        if self.order_exists(
            order.order_id
        ):
            raise DuplicateStoredOrderError(
                f"Order {order.order_id} "
                "already exists."
            )

        stored = StoredOrder(
            order_id=order.order_id,
            ticker=order.ticker.strip().upper(),
            side=order.side.value,
            quantity=order.quantity,
            signal_timestamp_utc=utc_iso(
                order.signal_timestamp_utc
            ),
            execution_session=(
                order.execution_session
            ),
            status=OrderStatus.PENDING.value,

            # Only legacy callers populate the legacy
            # column. New callers can leave it empty.
            source_run_id=source_run_id,

            model_version=model_version,
            created_at_utc=utc_iso(
                datetime.now(
                    timezone.utc
                )
            ),
        )

        try:
            with Session(
                self.engine
            ) as session:

                session.add(
                    stored
                )

                if (
                    resolved_decision_run_id
                    is not None
                ):
                    session.add(
                        StoredOrderDecisionLineage(
                            order_id=order.order_id,
                            decision_run_id=(
                                resolved_decision_run_id
                            ),
                        )
                    )

                # Order + lineage succeed or fail together.
                session.commit()

        except IntegrityError as exc:
            raise TradingStorageError(
                f"Failed to save order "
                f"{order.order_id}. "
                "The decision/source run ID "
                "may be invalid."
            ) from exc

        except Exception as exc:
            raise TradingStorageError(
                f"Failed to save order "
                f"{order.order_id}: {exc}"
            ) from exc

        return PersistedOrderResult(
            order_id=order.order_id,
            database_path=self.database_path,
        )

    def save_fill(
        self,
        fill: Fill,
        source_run_id: str | None = None,
        execution_run_id: str | None = None,
    ) -> PersistedFillResult:
        """
        Persist one fill.

        Preferred new argument:
            execution_run_id

        Legacy argument still supported:
            source_run_id
        """

        resolved_execution_run_id = (
            self._resolve_lineage_id(
                explicit_id=execution_run_id,
                legacy_id=source_run_id,
                explicit_name="execution_run_id",
                legacy_name="source_run_id",
            )
        )

        fill_id = str(
            uuid4()
        )

        try:
            with Session(
                self.engine
            ) as session:

                order = session.get(
                    StoredOrder,
                    fill.order_id,
                )

                if order is None:
                    raise StoredOrderNotFoundError(
                        f"Order {fill.order_id} "
                        "must be stored before its fill."
                    )

                if (
                    order.status
                    == OrderStatus.FILLED.value
                ):
                    raise DuplicateStoredOrderError(
                        f"Order {fill.order_id} "
                        "has already been filled."
                    )

                if (
                    order.status
                    != OrderStatus.PENDING.value
                ):
                    raise InvalidStoredOrderStateError(
                        f"Order {fill.order_id} "
                        f"has status {order.status} "
                        "and cannot be filled."
                    )

                stored_fill = StoredFill(
                    fill_id=fill_id,
                    order_id=fill.order_id,
                    ticker=(
                        fill.ticker
                        .strip()
                        .upper()
                    ),
                    side=fill.side.value,
                    quantity=fill.quantity,
                    execution_session=(
                        fill.execution_session
                    ),
                    reference_price=(
                        fill.reference_price
                    ),
                    fill_price=fill.fill_price,
                    gross_value=fill.gross_value,
                    fees=fill.fees,
                    slippage_cost=(
                        fill.slippage_cost
                    ),
                    realized_pnl=(
                        fill.realized_pnl
                    ),

                    # Only legacy callers populate this.
                    source_run_id=source_run_id,

                    created_at_utc=utc_iso(
                        datetime.now(
                            timezone.utc
                        )
                    ),
                )

                session.add(
                    stored_fill
                )

                if (
                    resolved_execution_run_id
                    is not None
                ):
                    session.add(
                        StoredFillExecutionLineage(
                            fill_id=fill_id,
                            execution_run_id=(
                                resolved_execution_run_id
                            ),
                        )
                    )

                order.status = (
                    OrderStatus.FILLED.value
                )

                # Fill + lineage + state transition
                # are committed atomically.
                session.commit()

        except DuplicateStoredOrderError:
            raise

        except StoredOrderNotFoundError:
            raise

        except InvalidStoredOrderStateError:
            raise

        except IntegrityError as exc:
            raise TradingStorageError(
                f"Failed to persist fill "
                f"for order {fill.order_id}. "
                "The execution/source run ID "
                "may be invalid."
            ) from exc

        except Exception as exc:
            raise TradingStorageError(
                f"Failed to save fill "
                f"for {fill.order_id}: {exc}"
            ) from exc

        return PersistedFillResult(
            fill_id=fill_id,
            order_id=fill.order_id,
            database_path=self.database_path,
        )

    def reject_order(
        self,
        order_id: str,
        rejection_code: str,
        rejection_reason: str,
    ) -> StoredOrderRejectionRecord:

        rejection_code = (
            rejection_code.strip()
        )

        rejection_reason = (
            rejection_reason.strip()
        )

        if not rejection_code:
            raise ValueError(
                "rejection_code cannot be empty."
            )

        if not rejection_reason:
            raise ValueError(
                "rejection_reason cannot be empty."
            )

        rejected_at_utc = utc_iso(
            datetime.now(
                timezone.utc
            )
        )

        try:
            with Session(
                self.engine
            ) as session:

                order = session.get(
                    StoredOrder,
                    order_id,
                )

                if order is None:
                    raise StoredOrderNotFoundError(
                        f"Order {order_id} "
                        "does not exist."
                    )

                if (
                    order.status
                    != OrderStatus.PENDING.value
                ):
                    raise InvalidStoredOrderStateError(
                        f"Order {order_id} "
                        f"has status {order.status} "
                        "and cannot transition "
                        "to REJECTED."
                    )

                rejection = (
                    StoredOrderRejection(
                        order_id=order_id,
                        rejection_code=(
                            rejection_code
                        ),
                        rejection_reason=(
                            rejection_reason
                        ),
                        rejected_at_utc=(
                            rejected_at_utc
                        ),
                    )
                )

                session.add(
                    rejection
                )

                order.status = (
                    OrderStatus.REJECTED.value
                )

                session.commit()

        except StoredOrderNotFoundError:
            raise

        except InvalidStoredOrderStateError:
            raise

        except IntegrityError as exc:
            raise TradingStorageError(
                f"Could not reject order "
                f"{order_id}: rejection already "
                "exists or database integrity failed."
            ) from exc

        except Exception as exc:
            raise TradingStorageError(
                f"Failed to reject order "
                f"{order_id}: {exc}"
            ) from exc

        return StoredOrderRejectionRecord(
            order_id=order_id,
            rejection_code=rejection_code,
            rejection_reason=rejection_reason,
            rejected_at_utc=rejected_at_utc,
        )

    def save_portfolio_snapshot(
        self,
        portfolio: Portfolio,
        prices: dict,
        session_date: date,
        recorded_at_utc: datetime | None = None,
    ) -> PersistedPortfolioSnapshotResult:

        if recorded_at_utc is None:
            recorded_at_utc = datetime.now(
                timezone.utc
            )

        if recorded_at_utc.tzinfo is None:
            raise ValueError(
                "recorded_at_utc must be "
                "timezone-aware."
            )

        market_value = (
            portfolio.market_value(
                prices
            )
        )

        unrealized = (
            portfolio.unrealized_pnl(
                prices
            )
        )

        total_equity = (
            portfolio.total_equity(
                prices
            )
        )

        snapshot_id = str(
            uuid4()
        )

        snapshot = StoredPortfolioSnapshot(
            snapshot_id=snapshot_id,
            recorded_at_utc=utc_iso(
                recorded_at_utc
            ),
            session_date=session_date,
            cash=portfolio.cash,
            market_value=market_value,
            total_equity=total_equity,
            realized_pnl=(
                portfolio.realized_pnl
            ),
            unrealized_pnl=unrealized,
            open_position_count=len(
                portfolio.positions
            ),
        )

        try:
            with Session(
                self.engine
            ) as session:

                session.add(
                    snapshot
                )

                session.commit()

        except Exception as exc:
            raise TradingStorageError(
                "Failed to save portfolio "
                f"snapshot: {exc}"
            ) from exc

        return PersistedPortfolioSnapshotResult(
            snapshot_id=snapshot_id,
            database_path=self.database_path,
        )

    def list_fills(
        self,
    ) -> list[StoredFillRecord]:

        with Session(
            self.engine
        ) as session:

            statement = (
                select(
                    StoredFill
                )
                .order_by(
                    StoredFill
                    .execution_session
                    .asc(),
                    StoredFill
                    .created_at_utc
                    .asc(),
                    StoredFill
                    .fill_id
                    .asc(),
                )
            )

            records = session.scalars(
                statement
            ).all()

            lineage_rows = session.scalars(
                select(
                    StoredFillExecutionLineage
                )
            ).all()

            execution_lineage = {
                row.fill_id: (
                    row.execution_run_id
                )
                for row in lineage_rows
            }

            return [
                StoredFillRecord(
                    fill_id=row.fill_id,
                    order_id=row.order_id,
                    ticker=row.ticker,
                    side=row.side,
                    quantity=row.quantity,
                    execution_session=(
                        row.execution_session
                    ),
                    reference_price=money(
                        row.reference_price
                    ),
                    fill_price=money(
                        row.fill_price
                    ),
                    fees=money(
                        row.fees
                    ),
                    slippage_cost=money(
                        row.slippage_cost
                    ),
                    realized_pnl=money(
                        row.realized_pnl
                    ),
                    created_at_utc=(
                        row.created_at_utc
                    ),
                    execution_run_id=(
                        execution_lineage.get(
                            row.fill_id
                        )
                    ),
                )
                for row in records
            ]

    def get_order(
        self,
        order_id: str,
    ) -> StoredOrderRecord | None:

        with Session(
            self.engine
        ) as session:

            row = session.get(
                StoredOrder,
                order_id,
            )

            if row is None:
                return None

            lineage = session.get(
                StoredOrderDecisionLineage,
                order_id,
            )

            decision_run_id = (
                lineage.decision_run_id
                if lineage is not None
                else row.source_run_id
            )

            return StoredOrderRecord(
                order_id=row.order_id,
                ticker=row.ticker,
                side=row.side,
                quantity=row.quantity,
                signal_timestamp_utc=(
                    row.signal_timestamp_utc
                ),
                execution_session=(
                    row.execution_session
                ),
                status=row.status,
                source_run_id=(
                    row.source_run_id
                ),
                model_version=(
                    row.model_version
                ),
                decision_run_id=(
                    decision_run_id
                ),
            )

    def get_order_rejection(
        self,
        order_id: str,
    ) -> StoredOrderRejectionRecord | None:

        with Session(
            self.engine
        ) as session:

            row = session.get(
                StoredOrderRejection,
                order_id,
            )

            if row is None:
                return None

            return StoredOrderRejectionRecord(
                order_id=row.order_id,
                rejection_code=(
                    row.rejection_code
                ),
                rejection_reason=(
                    row.rejection_reason
                ),
                rejected_at_utc=(
                    row.rejected_at_utc
                ),
            )

    def order_exists(
        self,
        order_id: str,
    ) -> bool:

        with Session(
            self.engine
        ) as session:

            return (
                session.get(
                    StoredOrder,
                    order_id,
                )
                is not None
            )

    def get_order_status(
        self,
        order_id: str,
    ) -> str | None:

        with Session(
            self.engine
        ) as session:

            order = session.get(
                StoredOrder,
                order_id,
            )

            if order is None:
                return None

            return order.status

    def count_orders(
        self,
    ) -> int:

        with Session(
            self.engine
        ) as session:

            return len(
                session.scalars(
                    select(
                        StoredOrder
                    )
                ).all()
            )

    def count_fills(
        self,
    ) -> int:

        with Session(
            self.engine
        ) as session:

            return len(
                session.scalars(
                    select(
                        StoredFill
                    )
                ).all()
            )

    def count_portfolio_snapshots(
        self,
    ) -> int:

        with Session(
            self.engine
        ) as session:

            return len(
                session.scalars(
                    select(
                        StoredPortfolioSnapshot
                    )
                ).all()
            )