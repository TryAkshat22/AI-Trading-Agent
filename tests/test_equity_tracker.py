from datetime import date
from decimal import Decimal

from database.equity_storage import (
    EquityStorage,
)
from evaluation.equity_tracker import (
    EquityTracker,
)
from evaluation.portfolio_report import (
    PortfolioReport,
)


SESSION = date(
    2026,
    9,
    14,
)


class FakeReportService:

    def __init__(
        self,
    ) -> None:

        self.account_ids = []

    def build(
        self,
        account_id="model1-paper",
    ):

        self.account_ids.append(
            account_id
        )

        return PortfolioReport(
            account_id=account_id,
            starting_cash=Decimal(
                "10000"
            ),
            cash=Decimal(
                "9000"
            ),
            market_value=Decimal(
                "1100"
            ),
            total_equity=Decimal(
                "10100"
            ),
            realized_pnl=Decimal(
                "0"
            ),
            unrealized_pnl=Decimal(
                "100"
            ),
            total_pnl=Decimal(
                "100"
            ),
            total_return_pct=Decimal(
                "1"
            ),
            exposure_pct=Decimal(
                "10.891089"
            ),
            open_positions=1,
            trade_count=1,
            positions=(),
        )


def test_tracker_records_report(
    tmp_path,
):

    storage = EquityStorage(
        tmp_path
        / "tracker.db"
    )

    storage.initialize()

    service = (
        FakeReportService()
    )

    tracker = EquityTracker(
        portfolio_report_service=service,
        equity_storage=storage,
    )

    result = tracker.record(
        SESSION
    )

    assert (
        result.snapshot
        .valuation_session
        == SESSION
    )

    assert (
        result.snapshot
        .total_equity
        == Decimal(
            "10100"
        )
    )

    assert (
        storage.count_snapshots()
        == 1
    )


def test_tracker_uses_account_id(
    tmp_path,
):

    storage = EquityStorage(
        tmp_path
        / "tracker.db"
    )

    storage.initialize()

    service = FakeReportService()

    tracker = EquityTracker(
        portfolio_report_service=service,
        equity_storage=storage,
        account_id="model1-paper",
    )

    tracker.record(
        SESSION
    )

    assert (
        service.account_ids
        == [
            "model1-paper"
        ]
    )


def test_tracker_is_idempotent(
    tmp_path,
):

    storage = EquityStorage(
        tmp_path
        / "tracker.db"
    )

    storage.initialize()

    tracker = EquityTracker(
        portfolio_report_service=(
            FakeReportService()
        ),
        equity_storage=storage,
    )

    first = tracker.record(
        SESSION
    )

    second = tracker.record(
        SESSION
    )

    assert (
        first.snapshot.snapshot_id
        == second.snapshot.snapshot_id
    )

    assert (
        storage.count_snapshots()
        == 1
    )