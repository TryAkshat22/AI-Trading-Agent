from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from database.account_storage import (
    AccountStorage,
    DEFAULT_ACCOUNT_ID,
)
from database.trading_storage import TradingStorage
from risk.risk_engine import (
    RiskAssessment,
    RiskDecision,
    RiskEngine,
)
from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult
from trading.execution_price import (
    ExecutionPrice,
    resolve_execution_price,
)
from trading.execution_scheduler import (
    ExecutionPlan,
    ExecutionScheduler,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
    PaperBroker,
)
from trading.portfolio import money
from trading.portfolio_rebuilder import (
    rebuild_portfolio,
)


class ExecutionServiceError(Exception):
    """Base exception for execution-service failures."""


class PendingOrderNotFoundError(
    ExecutionServiceError
):
    """Raised when an order cannot be found."""


class OrderNotPendingError(
    ExecutionServiceError
):
    """Raised when a non-pending order is executed."""


class OrderConsistencyError(
    ExecutionServiceError
):
    """Raised when persisted order data is inconsistent."""


class ExecutionRiskRejectedError(
    ExecutionServiceError
):
    """
    Raised when execution-time risk rejects
    a previously prepared order.
    """

    def __init__(
        self,
        order_id: str,
        assessment: RiskAssessment,
    ) -> None:

        self.order_id = order_id
        self.assessment = assessment

        reasons = "; ".join(
            issue.message
            for issue in assessment.issues
        )

        super().__init__(
            f"Execution-time risk check rejected "
            f"order {order_id}: {reasons}"
        )


@dataclass(frozen=True)
class PreparedOrder:
    order: Order
    execution_plan: ExecutionPlan


@dataclass(frozen=True)
class ExecutedOrder:
    order: Order
    fill: Fill
    execution_price: ExecutionPrice
    execution_risk_assessment: RiskAssessment
    portfolio_snapshot_id: str | None


class ExecutionService:
    """
    Coordinates deterministic Model 1
    paper-order preparation and execution.

    Preferred lineage terminology:

        decision_run_id
            data used to produce an order

        execution_run_id
            data used to observe execution price

    Legacy argument names remain supported while
    existing code transitions safely.
    """

    def __init__(
        self,
        account_storage: AccountStorage,
        trading_storage: TradingStorage,
        scheduler: ExecutionScheduler | None = None,
        broker_config: BrokerConfig | None = None,
        risk_engine: RiskEngine | None = None,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> None:

        self.account_storage = account_storage
        self.trading_storage = trading_storage

        self.scheduler = (
            scheduler
            if scheduler is not None
            else ExecutionScheduler()
        )

        self.broker_config = (
            broker_config
            if broker_config is not None
            else BrokerConfig()
        )

        self.risk_engine = (
            risk_engine
            if risk_engine is not None
            else RiskEngine()
        )

        self.account_id = account_id

    @staticmethod
    def _resolve_lineage_id(
        explicit_id: str | None,
        legacy_id: str | None,
        explicit_name: str,
        legacy_name: str,
    ) -> str | None:

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

    def prepare_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: int,
        signal_timestamp: datetime,

        # Existing API — kept in its original position.
        source_run_id: str | None = None,

        model_version: str | None = None,
        order_id: str | None = None,

        # New explicit API.
        decision_run_id: str | None = None,
    ) -> PreparedOrder:
        """
        Schedule and persist a new PENDING order.

        New callers should use decision_run_id.

        Existing source_run_id callers remain valid.
        """

        ticker = (
            ticker
            .strip()
            .upper()
        )

        if not ticker:
            raise ValueError(
                "Ticker cannot be empty."
            )

        if quantity <= 0:
            raise ValueError(
                "Quantity must be positive."
            )

        resolved_decision_run_id = (
            self._resolve_lineage_id(
                explicit_id=decision_run_id,
                legacy_id=source_run_id,
                explicit_name="decision_run_id",
                legacy_name="source_run_id",
            )
        )

        execution_plan = (
            self.scheduler.create_plan(
                signal_timestamp
            )
        )

        if order_id is None:
            order_id = str(
                uuid4()
            )

        order = Order(
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            signal_timestamp_utc=(
                execution_plan
                .signal_timestamp_utc
            ),
            execution_session=(
                execution_plan
                .execution_session
            ),
        )

        self.trading_storage.save_order(
            order=order,

            # Preserve legacy field only if the
            # caller actually used the legacy API.
            source_run_id=source_run_id,

            model_version=model_version,

            decision_run_id=(
                resolved_decision_run_id
            ),
        )

        return PreparedOrder(
            order=order,
            execution_plan=execution_plan,
        )

    def execute_order(
        self,
        order_id: str,
        market_result: MarketDataResult,
        quality_report: DataQualityReport,

        # Existing API — original position retained.
        execution_snapshot_id: str | None = None,

        execution_market_prices: dict | None = None,
        valuation_prices: dict | None = None,
        recorded_at_utc: datetime | None = None,

        # New explicit API.
        execution_run_id: str | None = None,
    ) -> ExecutedOrder:
        """
        Execute one persisted PENDING order.

        New callers should use execution_run_id.

        Existing execution_snapshot_id callers
        remain valid.
        """

        resolved_execution_run_id = (
            self._resolve_lineage_id(
                explicit_id=execution_run_id,
                legacy_id=execution_snapshot_id,
                explicit_name="execution_run_id",
                legacy_name=(
                    "execution_snapshot_id"
                ),
            )
        )

        stored = (
            self.trading_storage
            .get_order(
                order_id
            )
        )

        if stored is None:
            raise PendingOrderNotFoundError(
                f"Order {order_id} does not exist."
            )

        if (
            stored.status
            != OrderStatus.PENDING.value
        ):
            raise OrderNotPendingError(
                f"Order {order_id} has status "
                f"{stored.status}, not PENDING."
            )

        signal_timestamp = (
            datetime.fromisoformat(
                stored
                .signal_timestamp_utc
                .replace(
                    "Z",
                    "+00:00",
                )
            )
        )

        side = OrderSide(
            stored.side
        )

        order = Order(
            order_id=stored.order_id,
            ticker=stored.ticker,
            side=side,
            quantity=stored.quantity,
            signal_timestamp_utc=(
                signal_timestamp
            ),
            execution_session=(
                stored.execution_session
            ),
        )

        execution_plan = (
            self.scheduler.create_plan(
                signal_timestamp
            )
        )

        if (
            execution_plan.execution_session
            != order.execution_session
        ):
            raise OrderConsistencyError(
                f"Persisted execution session "
                f"{order.execution_session} "
                "does not match scheduler result "
                f"{execution_plan.execution_session}."
            )

        portfolio = rebuild_portfolio(
            account_storage=(
                self.account_storage
            ),
            trading_storage=(
                self.trading_storage
            ),
            account_id=self.account_id,
        )

        execution_price = (
            resolve_execution_price(
                ticker=order.ticker,
                execution_plan=execution_plan,
                market_result=market_result,
                quality_report=quality_report,
                snapshot_id=(
                    resolved_execution_run_id
                ),
            )
        )

        projected_fill_price = (
            self._projected_fill_price(
                side=order.side,
                raw_open=(
                    execution_price.raw_open
                ),
            )
        )

        risk_prices = dict(
            execution_market_prices
            if execution_market_prices
            is not None
            else {}
        )

        risk_prices[
            order.ticker
        ] = execution_price.raw_open

        execution_risk = (
            self.risk_engine.assess(
                portfolio=portfolio,
                ticker=order.ticker,
                side=order.side,
                quantity=order.quantity,
                reference_price=(
                    projected_fill_price
                ),
                market_prices=risk_prices,
                estimated_fees=(
                    self.broker_config
                    .fee_per_trade
                ),
            )
        )

        if (
            execution_risk.decision
            != RiskDecision.APPROVE
        ):

            rejection_codes = ",".join(
                issue.code.value
                for issue
                in execution_risk.issues
            )

            rejection_reason = "; ".join(
                issue.message
                for issue
                in execution_risk.issues
            )

            self.trading_storage.reject_order(
                order_id=order.order_id,
                rejection_code=(
                    rejection_codes
                ),
                rejection_reason=(
                    rejection_reason
                ),
            )

            raise ExecutionRiskRejectedError(
                order_id=order.order_id,
                assessment=execution_risk,
            )

        broker = PaperBroker(
            portfolio=portfolio,
            config=self.broker_config,
        )

        fill = broker.execute(
            order=order,
            market_price=(
                execution_price.raw_open
            ),
            actual_session=(
                execution_price
                .execution_session
            ),
        )

        self.trading_storage.save_fill(
            fill=fill,

            # Preserve the legacy field only if the
            # old argument was used.
            source_run_id=(
                execution_snapshot_id
            ),

            execution_run_id=(
                resolved_execution_run_id
            ),
        )

        portfolio_snapshot_id = None

        if valuation_prices is not None:

            snapshot = (
                self.trading_storage
                .save_portfolio_snapshot(
                    portfolio=portfolio,
                    prices=valuation_prices,
                    session_date=(
                        fill.execution_session
                    ),
                    recorded_at_utc=(
                        recorded_at_utc
                    ),
                )
            )

            portfolio_snapshot_id = (
                snapshot.snapshot_id
            )

        return ExecutedOrder(
            order=order,
            fill=fill,
            execution_price=execution_price,
            execution_risk_assessment=(
                execution_risk
            ),
            portfolio_snapshot_id=(
                portfolio_snapshot_id
            ),
        )

    def _projected_fill_price(
        self,
        side: OrderSide,
        raw_open,
    ):

        raw_open = Decimal(
            str(raw_open)
        )

        slippage_bps = Decimal(
            str(
                self.broker_config
                .slippage_bps
            )
        )

        slippage_rate = (
            slippage_bps
            / Decimal("10000")
        )

        if side == OrderSide.BUY:

            projected = (
                raw_open
                * (
                    Decimal("1")
                    + slippage_rate
                )
            )

        elif side == OrderSide.SELL:

            projected = (
                raw_open
                * (
                    Decimal("1")
                    - slippage_rate
                )
            )

        else:
            raise ExecutionServiceError(
                f"Unsupported order side: "
                f"{side}"
            )

        return money(
            projected
        )