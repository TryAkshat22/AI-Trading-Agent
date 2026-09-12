from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from database.equity_storage import (
    EquitySnapshot,
    EquityStorage,
)
from evaluation.portfolio_report import (
    PortfolioReport,
    PortfolioReportService,
)


@dataclass(frozen=True)
class EquityTrackingResult:
    report: PortfolioReport
    snapshot: EquitySnapshot


class EquityTracker:
    """
    Converts a read-only portfolio report into
    one immutable daily equity snapshot.
    """

    def __init__(
        self,
        portfolio_report_service: PortfolioReportService,
        equity_storage: EquityStorage,
        account_id: str = "model1-paper",
        model_version: str = "model-1",
    ) -> None:

        self.portfolio_report_service = (
            portfolio_report_service
        )

        self.equity_storage = (
            equity_storage
        )

        self.account_id = (
            account_id
        )

        self.model_version = (
            model_version
        )

    def record(
        self,
        valuation_session: date,
    ) -> EquityTrackingResult:

        report = (
            self.portfolio_report_service
            .build(
                account_id=(
                    self.account_id
                )
            )
        )

        snapshot = (
            self.equity_storage
            .save_snapshot(
                valuation_session=(
                    valuation_session
                ),
                starting_cash=(
                    report.starting_cash
                ),
                cash=(
                    report.cash
                ),
                market_value=(
                    report.market_value
                ),
                total_equity=(
                    report.total_equity
                ),
                realized_pnl=(
                    report.realized_pnl
                ),
                unrealized_pnl=(
                    report.unrealized_pnl
                ),
                total_pnl=(
                    report.total_pnl
                ),
                total_return_pct=(
                    report.total_return_pct
                ),
                exposure_pct=(
                    report.exposure_pct
                ),
                open_positions=(
                    report.open_positions
                ),
                account_id=(
                    self.account_id
                ),
                model_version=(
                    self.model_version
                ),
            )
        )

        return EquityTrackingResult(
            report=report,
            snapshot=snapshot,
        )