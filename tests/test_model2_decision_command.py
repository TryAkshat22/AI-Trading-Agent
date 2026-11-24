
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from model2_decision_command import (
    Model2DecisionCommandError,
    check_after_close,
    order_id_for,
    run_model2_decision,
)


AFTER_CLOSE = datetime(
    2026, 9, 16, 20, 20,
    tzinfo=timezone.utc,
)


def test_regular_session_before_close_is_blocked():
    with pytest.raises(
        Model2DecisionCommandError,
        match="Too early",
    ):
        check_after_close(
            datetime(
                2026, 9, 16, 19, 0,
                tzinfo=timezone.utc,
            )
        )


def test_regular_session_after_close_is_allowed():
    assert check_after_close(
        AFTER_CLOSE
    ) == "2026-09-16"


def test_weekend_is_blocked():
    with pytest.raises(
        Model2DecisionCommandError,
        match="not an NYSE trading session",
    ):
        check_after_close(
            datetime(
                2026, 9, 19, 21, 0,
                tzinfo=timezone.utc,
            )
        )


def test_naive_datetime_is_blocked():
    with pytest.raises(
        Model2DecisionCommandError,
        match="timezone-aware",
    ):
        check_after_close(
            datetime(2026, 9, 16, 20, 20)
        )


def test_order_id_is_deterministic():
    assert order_id_for(
        "2026-09-16",
        "aapl",
    ) == "model-2-flexible-2026-09-16-AAPL"


def test_readiness_does_not_fetch_or_create_orders(
    tmp_path,
    monkeypatch,
    capsys,
):
    class FakeTradingStorage:
        def __init__(self):
            self.order_checks = 0

        def order_exists(self, order_id):
            self.order_checks += 1
            return False

    def unexpected_fetch(ticker):
        raise AssertionError(
            "Readiness mode must not fetch prices."
        )

    trading_storage = FakeTradingStorage()

    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    fake_components = SimpleNamespace(
        context=SimpleNamespace(
            model_version="model-2-flexible",
            account_id="model2-paper",
            database_path=model2,
            observation_database_path=model1,
            trading_storage=trading_storage,
        ),
        batch_runner=SimpleNamespace(
            tickers=("AAPL",),
            market_data_fetcher=unexpected_fetch,
        ),
    )

    monkeypatch.setattr(
        "model2_decision_command."
        "build_model2_decision_components",
        lambda: fake_components,
    )

    # This test covers readiness behavior, not the
    # SQLite ledger reader. Its database is intentionally
    # not initialized.
    monkeypatch.setattr(
        "model2_decision_command."
        "_existing_ledger_status",
        lambda database_path, decision_session: None,
    )

    result = run_model2_decision(
        execute=False,
        now=AFTER_CLOSE,
    )

    assert result is None
    assert trading_storage.order_checks == 1
    assert (
        "readiness: PASS"
        in capsys.readouterr().out
    )
    assert not model1.exists()
    assert not model2.exists()


def test_readiness_blocks_existing_order(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    fake_components = SimpleNamespace(
        context=SimpleNamespace(
            model_version="model-2-flexible",
            account_id="model2-paper",
            database_path=model2,
            observation_database_path=model1,
            trading_storage=SimpleNamespace(
                order_exists=lambda order_id: True
            ),
        ),
        batch_runner=SimpleNamespace(
            tickers=("AAPL",),
        ),
    )

    monkeypatch.setattr(
        "model2_decision_command."
        "build_model2_decision_components",
        lambda: fake_components,
    )

    with pytest.raises(
        Model2DecisionCommandError,
        match="already exists",
    ):
        run_model2_decision(
            execute=False,
            now=AFTER_CLOSE,
        )

    assert not model1.exists()
    assert not model2.exists()