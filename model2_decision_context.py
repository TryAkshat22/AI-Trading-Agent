
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)
from trading.decision_pipeline import DecisionPipeline
from trading.portfolio_rebuilder import PortfolioRebuilder


class Model2DecisionContextError(RuntimeError):
    """Model 2 cannot safely use the requested account."""


@dataclass(frozen=True)
class Model2DecisionContext:
    database_path: Path
    observation_database_path: Path
    account_id: str
    model_version: str
    starting_cash: Decimal
    account_storage: AccountStorage
    trading_storage: TradingStorage
    decision_pipeline: DecisionPipeline
    portfolio_rebuilder: PortfolioRebuilder


def build_model2_decision_context() -> Model2DecisionContext:
    """
    Connect existing decision components to Model 2.

    Does not initialize databases, fetch prices, generate
    decisions, create orders, or execute trades.
    """
    paths = get_model2_paths()

    if paths.model1_database == paths.model2_database:
        raise Model2DecisionContextError(
            "Model 1 and Model 2 database paths must differ."
        )

    if not paths.model2_database.is_file():
        raise Model2DecisionContextError(
            "Model 2 database is missing. "
            "Run model2_initialize.py --initialize first."
        )

    account_storage = AccountStorage(paths.model2_database)
    trading_storage = TradingStorage(paths.model2_database)

    account = account_storage.get_account(
        MODEL_2_ACCOUNT_ID
    )

    if account is None:
        raise Model2DecisionContextError(
            f"Model 2 account {MODEL_2_ACCOUNT_ID!r} "
            "does not exist in its database."
        )

    if account_storage.count_accounts() != 1:
        raise Model2DecisionContextError(
            "Model 2 database must contain exactly one account."
        )

    if account.starting_cash != Decimal("10000"):
        raise Model2DecisionContextError(
            "Model 2 starting cash differs from $10,000."
        )

    portfolio_rebuilder = PortfolioRebuilder(
        account_storage=account_storage,
        trading_storage=trading_storage,
    )

    # Verify that this account's persisted fills can be
    # replayed before connecting the decision pipeline.
    portfolio_rebuilder.rebuild(
        account_id=MODEL_2_ACCOUNT_ID
    )

    decision_pipeline = DecisionPipeline(
        account_storage=account_storage,
        trading_storage=trading_storage,
        account_id=MODEL_2_ACCOUNT_ID,
    )

    return Model2DecisionContext(
        database_path=paths.model2_database,
        observation_database_path=paths.observation_database,
        account_id=MODEL_2_ACCOUNT_ID,
        model_version=MODEL_2_VERSION,
        starting_cash=account.starting_cash,
        account_storage=account_storage,
        trading_storage=trading_storage,
        decision_pipeline=decision_pipeline,
        portfolio_rebuilder=portfolio_rebuilder,
    )