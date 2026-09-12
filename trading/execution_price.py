from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult
from trading.execution_scheduler import ExecutionPlan
from trading.portfolio import money


class ExecutionPriceError(Exception):
    """Base exception for execution-price resolution failures."""


class UnsafeSnapshotError(ExecutionPriceError):
    """Raised when execution is attempted from unsafe market data."""


class TickerMismatchError(ExecutionPriceError):
    """Raised when the requested ticker and snapshot ticker differ."""


class MissingExecutionSessionError(ExecutionPriceError):
    """Raised when the scheduled execution session is absent."""


class InvalidExecutionPriceError(ExecutionPriceError):
    """Raised when the raw execution price is missing or invalid."""


@dataclass(frozen=True)
class ExecutionPrice:
    ticker: str
    execution_session: date
    raw_open: Decimal

    provider: str

    # Optional snapshot/run identifier.
    # This leaves room for persistent ingestion-run IDs later.
    snapshot_id: str | None


class ExecutionPriceResolver:
    """
    Resolves the raw opening price for a scheduled paper-trade execution.

    Responsibilities:
    - verify data quality
    - verify ticker consistency
    - verify the execution session exists
    - read the RAW Open price
    - reject missing/invalid prices

    This class does not:
    - fetch market data
    - calculate slippage
    - execute trades
    - mutate the portfolio
    """

    def resolve(
        self,
        ticker: str,
        execution_plan: ExecutionPlan,
        market_result: MarketDataResult,
        quality_report: DataQualityReport,
        snapshot_id: str | None = None,
    ) -> ExecutionPrice:

        ticker = ticker.strip().upper()

        if not ticker:
            raise ValueError(
                "Ticker cannot be empty."
            )

        if not quality_report.safe_to_use:
            raise UnsafeSnapshotError(
                f"Refusing to resolve execution price "
                f"from unsafe data for {ticker}."
            )

        if ticker != market_result.ticker:
            raise TickerMismatchError(
                f"Requested ticker {ticker} does not match "
                f"market-data ticker {market_result.ticker}."
            )

        if ticker != quality_report.ticker:
            raise TickerMismatchError(
                f"Requested ticker {ticker} does not match "
                f"quality-report ticker {quality_report.ticker}."
            )

        execution_session = (
            execution_plan.execution_session
        )

        data = market_result.data.copy()

        if data.empty:
            raise MissingExecutionSessionError(
                f"No market data available for {ticker}."
            )

        session_dates = pd.to_datetime(
            data.index
        ).date

        matches = (
            session_dates
            == execution_session
        )

        if not matches.any():
            raise MissingExecutionSessionError(
                f"{ticker} does not contain execution session "
                f"{execution_session}."
            )

        matching_rows = data.loc[
            matches
        ]

        if len(matching_rows) != 1:
            raise ExecutionPriceError(
                f"Expected exactly one row for {ticker} on "
                f"{execution_session}, found "
                f"{len(matching_rows)}."
            )

        row = matching_rows.iloc[0]

        if "Open" not in row.index:
            raise InvalidExecutionPriceError(
                f"Raw Open price is missing for {ticker} "
                f"on {execution_session}."
            )

        raw_open = row["Open"]

        if pd.isna(raw_open):
            raise InvalidExecutionPriceError(
                f"Raw Open price is NaN for {ticker} "
                f"on {execution_session}."
            )

        raw_open = money(
            raw_open
        )

        if raw_open <= 0:
            raise InvalidExecutionPriceError(
                f"Raw Open price must be positive for "
                f"{ticker} on {execution_session}."
            )

        return ExecutionPrice(
            ticker=ticker,
            execution_session=execution_session,
            raw_open=raw_open,
            provider=market_result.provider,
            snapshot_id=snapshot_id,
        )


def resolve_execution_price(
    ticker: str,
    execution_plan: ExecutionPlan,
    market_result: MarketDataResult,
    quality_report: DataQualityReport,
    snapshot_id: str | None = None,
) -> ExecutionPrice:
    """
    Public execution-price resolution entry point.
    """

    resolver = ExecutionPriceResolver()

    return resolver.resolve(
        ticker=ticker,
        execution_plan=execution_plan,
        market_result=market_result,
        quality_report=quality_report,
        snapshot_id=snapshot_id,
    )