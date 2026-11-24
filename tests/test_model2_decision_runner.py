
from decimal import Decimal

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
)
from model2_decision_runner import (
    MODEL_2_TICKERS,
    build_model2_decision_components,
)


def configure_model2(tmp_path, monkeypatch):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    accounts = AccountStorage(model2)
    trading = TradingStorage(model2)

    accounts.initialize()
    trading.initialize()

    accounts.create_account(
        starting_cash=10000,
        account_id=MODEL_2_ACCOUNT_ID,
    )

    return model1, model2


def test_all_trading_components_use_model2_database(
    tmp_path,
    monkeypatch,
):
    model1, model2 = configure_model2(
        tmp_path,
        monkeypatch,
    )

    components = build_model2_decision_components()

    assert components.context.database_path == (
        model2.resolve()
    )

    assert components.market_storage.database_path == (
        model2.resolve()
    )

    assert (
        components.context.account_storage.database_path
        == model2.resolve()
    )

    assert (
        components.context.trading_storage.database_path
        == model2.resolve()
    )

    assert not model1.exists()


def test_decision_and_order_service_use_model2_account(
    tmp_path,
    monkeypatch,
):
    _, _ = configure_model2(
        tmp_path,
        monkeypatch,
    )

    components = build_model2_decision_components()

    assert (
        components.context.decision_pipeline.account_id
        == MODEL_2_ACCOUNT_ID
    )

    assert (
        components.execution_service.account_id
        == MODEL_2_ACCOUNT_ID
    )

    assert (
        components.orchestrator.model_version
        == MODEL_2_VERSION
    )


def test_runner_uses_expected_ticker_universe(
    tmp_path,
    monkeypatch,
):
    _, _ = configure_model2(
        tmp_path,
        monkeypatch,
    )

    components = build_model2_decision_components()

    assert components.batch_runner.tickers == (
        MODEL_2_TICKERS
    )

    assert (
        components.decision_runner.batch_runner
        is components.batch_runner
    )


def test_building_components_creates_no_orders_or_fills(
    tmp_path,
    monkeypatch,
):
    model1, model2 = configure_model2(
        tmp_path,
        monkeypatch,
    )

    components = build_model2_decision_components()

    trading = TradingStorage(model2)
    accounts = AccountStorage(model2)

    assert trading.count_orders() == 0
    assert trading.count_fills() == 0
    assert accounts.count_accounts() == 1

    account = accounts.get_account(
        MODEL_2_ACCOUNT_ID
    )

    assert account is not None
    assert account.starting_cash == Decimal("10000")
    assert not model1.exists()

    # The connected runner exists, but this test
    # intentionally does not invoke it.
    assert components.decision_runner is not None