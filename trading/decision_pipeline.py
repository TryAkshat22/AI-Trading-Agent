from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from database.account_storage import (
    AccountStorage,
    DEFAULT_ACCOUNT_ID,
)
from database.trading_storage import TradingStorage
from risk.position_sizer import (
    PositionSizeResult,
    PositionSizer,
)
from risk.risk_engine import (
    RiskAssessment,
    RiskDecision,
    RiskEngine,
)
from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult
from signals.signal_engine import (
    SignalAction,
    SignalEngine,
    SignalResult,
)
from trading.orders import OrderSide
from trading.portfolio_rebuilder import rebuild_portfolio


class DecisionPipelineError(Exception):
    """Base exception for decision-pipeline failures."""


class DecisionStatus(str, Enum):
    BUY_APPROVED = "BUY_APPROVED"
    EXIT_APPROVED = "EXIT_APPROVED"

    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"

    SIZE_ZERO = "SIZE_ZERO"
    RISK_REJECTED = "RISK_REJECTED"


@dataclass(frozen=True)
class TradeDecision:
    ticker: str
    status: DecisionStatus

    signal: SignalResult

    side: OrderSide | None
    quantity: int

    position_size: PositionSizeResult | None
    risk_assessment: RiskAssessment | None

    @property
    def approved_for_order(self) -> bool:
        return self.status in (
            DecisionStatus.BUY_APPROVED,
            DecisionStatus.EXIT_APPROVED,
        )


class DecisionPipeline:
    """
    Deterministic bridge between market analysis
    and order preparation.

    Responsibilities:
    1. Rebuild the portfolio from persistent fills.
    2. Determine whether the ticker is already owned.
    3. Generate a signal.
    4. Size BUY opportunities.
    5. Convert EXIT signals into full-position sells.
    6. Run the risk gate.
    7. Return an explicit final decision.

    This class does NOT:
    - execute orders
    - fetch market data
    - fetch execution prices
    - persist new orders
    """

    def __init__(
        self,
        account_storage: AccountStorage,
        trading_storage: TradingStorage,
        signal_engine: SignalEngine | None = None,
        position_sizer: PositionSizer | None = None,
        risk_engine: RiskEngine | None = None,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> None:

        self.account_storage = account_storage
        self.trading_storage = trading_storage

        self.signal_engine = (
            signal_engine
            if signal_engine is not None
            else SignalEngine()
        )

        self.position_sizer = (
            position_sizer
            if position_sizer is not None
            else PositionSizer()
        )

        self.risk_engine = (
            risk_engine
            if risk_engine is not None
            else RiskEngine()
        )

        self.account_id = account_id

    def evaluate(
        self,
        market_result: MarketDataResult,
        quality_report: DataQualityReport,
        market_prices: dict,
        estimated_fees=0,
    ) -> TradeDecision:

        ticker = (
            market_result.ticker
            .strip()
            .upper()
        )

        portfolio = rebuild_portfolio(
            account_storage=self.account_storage,
            trading_storage=self.trading_storage,
            account_id=self.account_id,
        )

        position = portfolio.get_position(
            ticker
        )

        has_position = (
            position is not None
            and position.quantity > 0
        )

        signal = self.signal_engine.generate(
            market_result=market_result,
            quality_report=quality_report,
            has_position=has_position,
        )

        # HOLD requires no order.
        if signal.action == SignalAction.HOLD:

            return TradeDecision(
                ticker=ticker,
                status=DecisionStatus.HOLD,
                signal=signal,
                side=None,
                quantity=0,
                position_size=None,
                risk_assessment=None,
            )

        # NO_TRADE requires no order.
        if signal.action == SignalAction.NO_TRADE:

            return TradeDecision(
                ticker=ticker,
                status=DecisionStatus.NO_TRADE,
                signal=signal,
                side=None,
                quantity=0,
                position_size=None,
                risk_assessment=None,
            )

        if signal.close is None:
            raise DecisionPipelineError(
                "Actionable signal does not contain "
                "a completed-session close price."
            )

        # BUY path.
        if signal.action == SignalAction.BUY:

            size = self.position_sizer.size_buy(
                portfolio=portfolio,
                ticker=ticker,
                reference_price=signal.close,
                market_prices=market_prices,
            )

            if not size.can_trade:

                return TradeDecision(
                    ticker=ticker,
                    status=DecisionStatus.SIZE_ZERO,
                    signal=signal,
                    side=OrderSide.BUY,
                    quantity=0,
                    position_size=size,
                    risk_assessment=None,
                )

            risk = self.risk_engine.assess(
                portfolio=portfolio,
                ticker=ticker,
                side=OrderSide.BUY,
                quantity=size.quantity,
                reference_price=signal.close,
                market_prices=market_prices,
                estimated_fees=estimated_fees,
            )

            if risk.decision != RiskDecision.APPROVE:

                return TradeDecision(
                    ticker=ticker,
                    status=DecisionStatus.RISK_REJECTED,
                    signal=signal,
                    side=OrderSide.BUY,
                    quantity=size.quantity,
                    position_size=size,
                    risk_assessment=risk,
                )

            return TradeDecision(
                ticker=ticker,
                status=DecisionStatus.BUY_APPROVED,
                signal=signal,
                side=OrderSide.BUY,
                quantity=size.quantity,
                position_size=size,
                risk_assessment=risk,
            )

        # EXIT path.
        if signal.action == SignalAction.EXIT:

            if position is None or position.quantity <= 0:
                raise DecisionPipelineError(
                    "EXIT signal was generated but "
                    "no open position exists."
                )

            quantity = position.quantity

            risk = self.risk_engine.assess(
                portfolio=portfolio,
                ticker=ticker,
                side=OrderSide.SELL,
                quantity=quantity,
                reference_price=signal.close,
                market_prices=market_prices,
                estimated_fees=estimated_fees,
            )

            if risk.decision != RiskDecision.APPROVE:

                return TradeDecision(
                    ticker=ticker,
                    status=DecisionStatus.RISK_REJECTED,
                    signal=signal,
                    side=OrderSide.SELL,
                    quantity=quantity,
                    position_size=None,
                    risk_assessment=risk,
                )

            return TradeDecision(
                ticker=ticker,
                status=DecisionStatus.EXIT_APPROVED,
                signal=signal,
                side=OrderSide.SELL,
                quantity=quantity,
                position_size=None,
                risk_assessment=risk,
            )

        raise DecisionPipelineError(
            f"Unsupported signal action: "
            f"{signal.action}"
        )