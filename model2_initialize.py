
from __future__ import annotations

import argparse
from decimal import Decimal

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from model2_config import (
    MODEL_2_ACCOUNT_ID,
    get_model2_paths,
)


STARTING_CASH = Decimal("10000")


def initialize_model2() -> None:
    paths = get_model2_paths()

    if paths.model1_database == paths.model2_database:
        raise RuntimeError(
            "Refusing to initialize Model 2 in the Model 1 database."
        )

    accounts = AccountStorage(paths.model2_database)
    trading = TradingStorage(paths.model2_database)

    accounts.initialize()
    trading.initialize()

    account = accounts.get_or_create(
        starting_cash=STARTING_CASH,
        account_id=MODEL_2_ACCOUNT_ID,
    )

    if account.account_id != MODEL_2_ACCOUNT_ID:
        raise RuntimeError("Unexpected Model 2 account identity.")

    if account.starting_cash != STARTING_CASH:
        raise RuntimeError(
            "Existing Model 2 account has different starting cash."
        )

    print("Model 2 initialization complete")
    print("===============================")
    print(f"Account: {account.account_id}")
    print(f"Starting cash: ${account.starting_cash:,.2f}")
    print(f"Database: {paths.model2_database}")
    print(f"Accounts: {accounts.count_accounts()}")
    print(f"Orders: {trading.count_orders()}")
    print(f"Fills: {trading.count_fills()}")
    print()
    print("No orders or fills were created by this command.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the isolated Model 2 paper account."
    )

    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Explicitly create or verify the Model 2 account.",
    )

    args = parser.parse_args()

    if not args.initialize:
        parser.print_help()
        return 0

    try:
        initialize_model2()
        return 0

    except Exception as exc:
        print(f"Initialization failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())