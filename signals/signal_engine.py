from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

import pandas as pd

from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult


class SignalEngineError(Exception):
    """Base exception for deterministic signal-generation failures."""


class UnsafeSignalDataError(SignalEngineError):
    """Raised when market data is not safe enough for signal generation."""


class SignalAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    EXIT = "EXIT"
    NO_TRADE = "NO_TRADE"


class SignalReason(str, Enum):
    BULLISH_TREND = "BULLISH_TREND"
    EXISTING_BULLISH_POSITION = "EXISTING_BULLISH_POSITION"

    TREND_FILTER_FAILED = "TREND_FILTER_FAILED"
    MOMENTUM_FILTER_FAILED = "MOMENTUM_FILTER_FAILED"

    EXIT_TREND_FAILED = "EXIT_TREND_FAILED"
    EXIT_MOMENTUM_FAILED = "EXIT_MOMENTUM_FAILED"

    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    UNSAFE_DATA = "UNSAFE_DATA"


@dataclass(frozen=True)
class SignalConfig:
    """
    Model 1 trend/momentum configuration.
    """

    sma_window: int = 50
    momentum_window: int = 20


@dataclass(frozen=True)
class SignalResult:
    ticker: str
    action: SignalAction
    reason: SignalReason

    source_session: date | None

    # Raw completed-session Close.
    #
    # This is kept as the economic reference price for
    # decision-time sizing/risk calculations.
    close: Decimal | None

    # Indicators below are calculated from Adj Close.
    moving_average: Decimal | None
    momentum: Decimal | None

    bars_used: int

    @property
    def actionable(self) -> bool:
        return self.action in (
            SignalAction.BUY,
            SignalAction.EXIT,
        )


class SignalEngine:
    """
    Deterministic Model 1 daily signal engine.

    IMPORTANT PRICE POLICY

    Raw Close:
        Used as the completed-session reference price.

    Adjusted Close:
        Used for historical comparisons such as:
        - moving average
        - momentum

    This prevents stock splits/dividends from creating
    artificial historical price shocks in indicators.

    ENTRY:
        adjusted close > adjusted SMA
        AND
        adjusted momentum > 0

    Existing position:
        bullish conditions remain -> HOLD
        either filter fails -> EXIT

    No existing position:
        bullish conditions pass -> BUY
        otherwise -> NO_TRADE

    Only fully completed sessions may contribute.
    """

    def __init__(
        self,
        config: SignalConfig | None = None,
    ) -> None:

        self.config = (
            config
            if config is not None
            else SignalConfig()
        )

        self._validate_config()

    def generate(
        self,
        market_result: MarketDataResult,
        quality_report: DataQualityReport,
        has_position: bool = False,
    ) -> SignalResult:

        ticker = (
            market_result.ticker
            .strip()
            .upper()
        )

        if not quality_report.safe_to_use:
            raise UnsafeSignalDataError(
                f"{ticker} market data failed "
                "the data-quality gate."
            )

        if (
            quality_report.ticker
            .strip()
            .upper()
            != ticker
        ):
            raise SignalEngineError(
                "Market-data ticker and "
                "quality-report ticker do not match."
            )

        expected_session = (
            quality_report
            .latest_expected_completed_session
        )

        if expected_session is None:
            raise UnsafeSignalDataError(
                "No completed market session is available."
            )

        data = market_result.data.copy()

        if data.empty:
            raise UnsafeSignalDataError(
                f"No market data available for {ticker}."
            )

        # Raw Close is required for decision-time
        # reference pricing.
        if "Close" not in data.columns:
            raise UnsafeSignalDataError(
                "Close column is required "
                "for signal generation."
            )

        # Adjusted Close is required for indicators.
        if "Adj Close" not in data.columns:
            raise UnsafeSignalDataError(
                "Adj Close column is required "
                "for historical signal calculations."
            )

        data.index = pd.to_datetime(
            data.index
        )

        # Anti-lookahead:
        # remove anything after the latest fully
        # completed exchange session.
        completed_data = data[
            data.index.date <= expected_session
        ].copy()

        completed_data = (
            completed_data
            .sort_index()
        )

        if completed_data.empty:
            raise UnsafeSignalDataError(
                "No completed bars are available "
                "for the expected market session."
            )

        actual_latest_session = (
            completed_data.index[-1].date()
        )

        # The exact completed session expected by the
        # quality report must exist in the data.
        if actual_latest_session != expected_session:
            raise UnsafeSignalDataError(
                "Market data does not contain the "
                "latest expected completed session. "
                f"Expected {expected_session}, "
                f"found {actual_latest_session}."
            )

        required_bars = max(
            self.config.sma_window,
            self.config.momentum_window + 1,
        )

        if len(completed_data) < required_bars:

            return SignalResult(
                ticker=ticker,
                action=SignalAction.NO_TRADE,
                reason=SignalReason.INSUFFICIENT_HISTORY,
                source_session=actual_latest_session,
                close=None,
                moving_average=None,
                momentum=None,
                bars_used=len(completed_data),
            )

        raw_closes = completed_data[
            "Close"
        ].astype(float)

        adjusted_closes = completed_data[
            "Adj Close"
        ].astype(float)

        if raw_closes.isna().any():
            raise UnsafeSignalDataError(
                "Completed-session Close data "
                "contains missing values."
            )

        if adjusted_closes.isna().any():
            raise UnsafeSignalDataError(
                "Completed-session Adj Close data "
                "contains missing values."
            )

        if (raw_closes <= 0).any():
            raise UnsafeSignalDataError(
                "Completed-session Close prices "
                "must be positive."
            )

        if (adjusted_closes <= 0).any():
            raise UnsafeSignalDataError(
                "Completed-session Adj Close prices "
                "must be positive."
            )

        # Raw latest close:
        # used later by sizing/risk as the known
        # completed-session price.
        latest_raw_close = Decimal(
            str(
                raw_closes.iloc[-1]
            )
        )

        # Adjusted latest close:
        # used only for historical indicators.
        latest_adjusted_close = Decimal(
            str(
                adjusted_closes.iloc[-1]
            )
        )

        moving_average = Decimal(
            str(
                adjusted_closes
                .tail(
                    self.config.sma_window
                )
                .mean()
            )
        )

        momentum_start = (
            adjusted_closes.iloc[
                -(
                    self.config
                    .momentum_window
                    + 1
                )
            ]
        )

        momentum = Decimal(
            str(
                (
                    adjusted_closes.iloc[-1]
                    / momentum_start
                )
                - 1
            )
        )

        trend_pass = (
            latest_adjusted_close
            > moving_average
        )

        momentum_pass = (
            momentum
            > Decimal("0")
        )

        # -----------------------------------------
        # EXISTING POSITION
        # -----------------------------------------

        if has_position:

            if not trend_pass:

                return SignalResult(
                    ticker=ticker,
                    action=SignalAction.EXIT,
                    reason=(
                        SignalReason
                        .EXIT_TREND_FAILED
                    ),
                    source_session=(
                        actual_latest_session
                    ),
                    close=latest_raw_close,
                    moving_average=(
                        moving_average
                    ),
                    momentum=momentum,
                    bars_used=len(
                        completed_data
                    ),
                )

            if not momentum_pass:

                return SignalResult(
                    ticker=ticker,
                    action=SignalAction.EXIT,
                    reason=(
                        SignalReason
                        .EXIT_MOMENTUM_FAILED
                    ),
                    source_session=(
                        actual_latest_session
                    ),
                    close=latest_raw_close,
                    moving_average=(
                        moving_average
                    ),
                    momentum=momentum,
                    bars_used=len(
                        completed_data
                    ),
                )

            return SignalResult(
                ticker=ticker,
                action=SignalAction.HOLD,
                reason=(
                    SignalReason
                    .EXISTING_BULLISH_POSITION
                ),
                source_session=(
                    actual_latest_session
                ),
                close=latest_raw_close,
                moving_average=(
                    moving_average
                ),
                momentum=momentum,
                bars_used=len(
                    completed_data
                ),
            )

        # -----------------------------------------
        # NO EXISTING POSITION
        # -----------------------------------------

        if not trend_pass:

            return SignalResult(
                ticker=ticker,
                action=SignalAction.NO_TRADE,
                reason=(
                    SignalReason
                    .TREND_FILTER_FAILED
                ),
                source_session=(
                    actual_latest_session
                ),
                close=latest_raw_close,
                moving_average=(
                    moving_average
                ),
                momentum=momentum,
                bars_used=len(
                    completed_data
                ),
            )

        if not momentum_pass:

            return SignalResult(
                ticker=ticker,
                action=SignalAction.NO_TRADE,
                reason=(
                    SignalReason
                    .MOMENTUM_FILTER_FAILED
                ),
                source_session=(
                    actual_latest_session
                ),
                close=latest_raw_close,
                moving_average=(
                    moving_average
                ),
                momentum=momentum,
                bars_used=len(
                    completed_data
                ),
            )

        return SignalResult(
            ticker=ticker,
            action=SignalAction.BUY,
            reason=SignalReason.BULLISH_TREND,
            source_session=(
                actual_latest_session
            ),
            close=latest_raw_close,
            moving_average=(
                moving_average
            ),
            momentum=momentum,
            bars_used=len(
                completed_data
            ),
        )

    def _validate_config(
        self,
    ) -> None:

        if self.config.sma_window < 2:
            raise ValueError(
                "sma_window must be at least 2."
            )

        if self.config.momentum_window < 1:
            raise ValueError(
                "momentum_window must be at least 1."
            )


def generate_signal(
    market_result: MarketDataResult,
    quality_report: DataQualityReport,
    has_position: bool = False,
    config: SignalConfig | None = None,
) -> SignalResult:

    engine = SignalEngine(
        config=config
    )

    return engine.generate(
        market_result=market_result,
        quality_report=quality_report,
        has_position=has_position,
    )