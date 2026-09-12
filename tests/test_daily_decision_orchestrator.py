from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pandas as pd
import pytest

from database.storage import (
    MarketDataStorage,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.daily_decision_orchestrator import (
    DailyDecisionOrchestrator,
    InvalidDecisionArgumentsError,
    MissingModelVersionError,
)


def make_market_result(
) -> MarketDataResult:

    data = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime(
            [
                "2026-09-04",
            ]
        ),
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="test",
        retrieved_at_utc=datetime(
            2026,
            9,
            4,
            21,
            5,
            tzinfo=timezone.utc,
        ),
    )


def make_quality_report(
) -> DataQualityReport:

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            4,
            21,
            6,
            tzinfo=timezone.utc,
        ),
        latest_data_session=date(
            2026,
            9,
            4,
        ),
        latest_expected_completed_session=date(
            2026,
            9,
            4,
        ),
        issues=(),
    )


def valid_decision_timestamp(
) -> datetime:

    return datetime(
        2026,
        9,
        4,
        21,
        10,
        tzinfo=timezone.utc,
    )


class FakeDecisionPipeline:

    def __init__(self):

        self.calls = []

        self.decision = SimpleNamespace(
            status="NO_TRADE",
            signal=SimpleNamespace(
                ticker="AAPL",
                source_session=date(
                    2026,
                    9,
                    4,
                ),
            ),
            side=None,
            quantity=None,
        )

    def evaluate(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        return self.decision


class FakeCoordinator:

    def __init__(self):

        self.calls = []

    def coordinate(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        return SimpleNamespace(
            order_created=False,
            prepared_order=None,
        )


def make_orchestrator(
    tmp_path,
):

    database_path = (
        tmp_path
        / "test.db"
    )

    market_storage = (
        MarketDataStorage(
            database_path
        )
    )

    market_storage.initialize()

    pipeline = (
        FakeDecisionPipeline()
    )

    coordinator = (
        FakeCoordinator()
    )

    orchestrator = (
        DailyDecisionOrchestrator(
            market_storage=(
                market_storage
            ),
            decision_pipeline=(
                pipeline
            ),
            coordinator=(
                coordinator
            ),
            model_version=(
                "model-1"
            ),
        )
    )

    return (
        market_storage,
        pipeline,
        coordinator,
        orchestrator,
    )


def test_daily_cycle_persists_decision_snapshot(
    tmp_path,
):

    (
        market_storage,
        _,
        _,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    result = orchestrator.run(
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
        decision_timestamp=(
            valid_decision_timestamp()
        ),
    )

    assert (
        result.decision_run_id
        is not None
    )

    assert (
        market_storage
        .count_ingestion_runs()
        == 1
    )


def test_pipeline_receives_same_market_data(
    tmp_path,
):

    (
        _,
        pipeline,
        _,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    market_result = (
        make_market_result()
    )

    quality_report = (
        make_quality_report()
    )

    orchestrator.run(
        market_result=market_result,
        quality_report=quality_report,
        decision_timestamp=(
            valid_decision_timestamp()
        ),
    )

    assert (
        len(
            pipeline.calls
        )
        == 1
    )

    call = pipeline.calls[0]

    assert (
        call["market_result"]
        is market_result
    )

    assert (
        call["quality_report"]
        is quality_report
    )


def test_decision_run_id_is_forwarded_to_coordinator(
    tmp_path,
):

    (
        _,
        _,
        coordinator,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    result = orchestrator.run(
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
        decision_timestamp=(
            valid_decision_timestamp()
        ),
        order_id="order-1",
    )

    assert (
        len(
            coordinator.calls
        )
        == 1
    )

    call = (
        coordinator.calls[0]
    )

    assert (
        call["decision_run_id"]
        == result.decision_run_id
    )

    assert (
        call["model_version"]
        == "model-1"
    )

    assert (
        call["order_id"]
        == "order-1"
    )


def test_additional_decision_arguments_are_forwarded(
    tmp_path,
):

    (
        _,
        pipeline,
        _,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    prices = {
        "AAPL": 101.0,
        "MSFT": 250.0,
    }

    orchestrator.run(
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
        decision_timestamp=(
            valid_decision_timestamp()
        ),
        decision_kwargs={
            "market_prices": prices,
        },
    )

    assert (
        pipeline.calls[0][
            "market_prices"
        ]
        is prices
    )


def test_market_result_cannot_be_overridden(
    tmp_path,
):

    (
        market_storage,
        pipeline,
        coordinator,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    with pytest.raises(
        InvalidDecisionArgumentsError
    ):
        orchestrator.run(
            market_result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
            decision_timestamp=(
                valid_decision_timestamp()
            ),
            decision_kwargs={
                "market_result": (
                    make_market_result()
                ),
            },
        )

    # Failure occurs before persistence
    # or decision generation.
    assert (
        market_storage
        .count_ingestion_runs()
        == 0
    )

    assert pipeline.calls == []

    assert coordinator.calls == []


def test_quality_report_cannot_be_overridden(
    tmp_path,
):

    (
        market_storage,
        pipeline,
        coordinator,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    with pytest.raises(
        InvalidDecisionArgumentsError
    ):
        orchestrator.run(
            market_result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
            decision_timestamp=(
                valid_decision_timestamp()
            ),
            decision_kwargs={
                "quality_report": (
                    make_quality_report()
                ),
            },
        )

    assert (
        market_storage
        .count_ingestion_runs()
        == 0
    )

    assert pipeline.calls == []

    assert coordinator.calls == []


def test_empty_model_version_is_rejected(
    tmp_path,
):

    database_path = (
        tmp_path
        / "test.db"
    )

    market_storage = (
        MarketDataStorage(
            database_path
        )
    )

    market_storage.initialize()

    with pytest.raises(
        MissingModelVersionError
    ):
        DailyDecisionOrchestrator(
            market_storage=(
                market_storage
            ),
            decision_pipeline=(
                FakeDecisionPipeline()
            ),
            coordinator=(
                FakeCoordinator()
            ),
            model_version="   ",
        )


def test_order_created_property_is_forwarded(
    tmp_path,
):

    (
        _,
        _,
        coordinator,
        orchestrator,
    ) = make_orchestrator(
        tmp_path
    )

    class CreatedCoordinator:

        def coordinate(
            self,
            **kwargs,
        ):

            return SimpleNamespace(
                order_created=True,
                prepared_order=(
                    SimpleNamespace(
                        order=(
                            SimpleNamespace(
                                order_id="order-1"
                            )
                        )
                    )
                ),
            )

    orchestrator.coordinator = (
        CreatedCoordinator()
    )

    result = orchestrator.run(
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
        decision_timestamp=(
            valid_decision_timestamp()
        ),
    )

    assert result.order_created

    assert (
        result.prepared_order
        is not None
    )