from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)
from database.trading_storage import TradingStorage
from trading.orders import Order, OrderSide


CONFIRMATION_TEXT = "PREPARE-MODEL2-TRIAL"
NEW_YORK = ZoneInfo("America/New_York")


class ControlledTrialPreparationError(RuntimeError):
    """The controlled Model 2 trial order could not be prepared."""


def _backup_path(database: Path) -> Path:
    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    return database.with_name(
        f"{database.stem}"
        f"_pre_controlled_trial_{stamp}"
        f"{database.suffix}"
    )


def _read_scalar(
    connection: sqlite3.Connection,
    query: str,
    parameters=(),
) -> int:
    return int(
        connection.execute(
            query,
            parameters,
        ).fetchone()[0]
    )


def inspect_before_trial(
    database: Path,
) -> None:
    uri = database.as_uri() + "?mode=ro"

    with sqlite3.connect(
        uri,
        uri=True,
        timeout=10,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        account_rows = connection.execute(
            """
            SELECT account_id
            FROM paper_accounts
            """
        ).fetchall()

        if account_rows != [
            (MODEL_2_ACCOUNT_ID,)
        ]:
            raise ControlledTrialPreparationError(
                "Unexpected Model 2 account configuration."
            )

        pending = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM paper_orders
            WHERE status = 'PENDING'
            """,
        )

        fills = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM paper_fills
            """,
        )

        attempts = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM execution_attempts
            """,
        )

        execution_lineage = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM fill_execution_lineage
            """,
        )

        if pending != 0:
            raise ControlledTrialPreparationError(
                f"Expected 0 pending orders; found {pending}."
            )

        if fills != 0:
            raise ControlledTrialPreparationError(
                f"Expected 0 fills before first trial; found {fills}."
            )

        if attempts != 0:
            raise ControlledTrialPreparationError(
                "Expected 0 execution attempts before first "
                f"trial; found {attempts}."
            )

        if execution_lineage != 0:
            raise ControlledTrialPreparationError(
                "Expected empty fill execution lineage."
            )


def prepare_controlled_trial(
    *,
    execution_session: date,
    ticker: str,
    apply: bool,
    confirmation: str,
) -> str:
    ticker = ticker.strip().upper()

    if not ticker:
        raise ControlledTrialPreparationError(
            "Ticker cannot be blank."
        )

    if not ticker.replace(".", "").replace("-", "").isalnum():
        raise ControlledTrialPreparationError(
            "Ticker contains unsupported characters."
        )

    now_utc = datetime.now(timezone.utc)
    today_ny = now_utc.astimezone(
        NEW_YORK
    ).date()

    if execution_session <= today_ny:
        raise ControlledTrialPreparationError(
            "Controlled trial session must be in the future."
        )

    if execution_session.weekday() >= 5:
        raise ControlledTrialPreparationError(
            "Controlled trial session cannot be Saturday "
            "or Sunday."
        )

    paths = get_model2_paths()

    model1_db = Path(
        paths.model1_database
    ).expanduser().resolve()

    model2_db = Path(
        paths.model2_database
    ).expanduser().resolve()

    observation_db = Path(
        paths.observation_database
    ).expanduser().resolve()

    if model2_db == model1_db:
        raise ControlledTrialPreparationError(
            "Model 2 database resolves to Model 1."
        )

    if model2_db == observation_db:
        raise ControlledTrialPreparationError(
            "Model 2 database resolves to observation database."
        )

    if not model2_db.is_file():
        raise ControlledTrialPreparationError(
            "Model 2 database does not exist."
        )

    inspect_before_trial(
        model2_db
    )

    order_id = (
        "model-2-controlled-trial-"
        f"{execution_session.isoformat()}-"
        f"{ticker}"
    )

    with sqlite3.connect(
        model2_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        existing = connection.execute(
            """
            SELECT
                status,
                model_version
            FROM paper_orders
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

    if existing is not None:
        raise ControlledTrialPreparationError(
            "Controlled-trial order already exists: "
            f"{order_id}"
        )

    print()
    print("MODEL 2 CONTROLLED TRIAL PREPARATION")
    print("====================================")
    print()
    print(f"Database:          {model2_db}")
    print(f"Order ID:          {order_id}")
    print(f"Ticker:            {ticker}")
    print("Side:              BUY")
    print("Quantity:          1")
    print(
        f"Execution session: {execution_session}"
    )
    print(
        f"Model version:     {MODEL_2_VERSION}"
    )
    print()
    print(
        "This is a PAPER-TRADING infrastructure trial."
    )
    print(
        "It does not represent an investment recommendation."
    )
    print()

    if not apply:
        print("DRY RUN ONLY")
        print("------------")
        print(
            "No database changes were made."
        )
        print()
        print(
            "To create this single pending order, rerun "
            "with --apply and the confirmation token."
        )

        return order_id

    if confirmation != CONFIRMATION_TEXT:
        raise ControlledTrialPreparationError(
            "Correct confirmation token was not supplied."
        )

    backup = _backup_path(
        model2_db
    )

    shutil.copy2(
        model2_db,
        backup,
    )

    if not backup.is_file():
        raise ControlledTrialPreparationError(
            "Pre-trial backup could not be verified."
        )

    print("BACKUP")
    print("------")
    print(backup)
    print()

    order = Order(
        order_id=order_id,
        ticker=ticker,
        side=OrderSide.BUY,
        quantity=1,
        signal_timestamp_utc=now_utc,
        execution_session=execution_session,
    )

    storage = TradingStorage(
        model2_db
    )

    storage.save_order(
        order,
        model_version=MODEL_2_VERSION,
    )

    # Verify exactly what was written.
    with sqlite3.connect(
        model2_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        row = connection.execute(
            """
            SELECT
                order_id,
                ticker,
                side,
                quantity,
                execution_session,
                status,
                model_version
            FROM paper_orders
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

        pending_count = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM paper_orders
            WHERE status = 'PENDING'
            """,
        )

        fill_count = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM paper_fills
            """,
        )

        attempt_count = _read_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM execution_attempts
            """,
        )

    expected = (
        order_id,
        ticker,
        "BUY",
        1,
        execution_session.isoformat(),
        "PENDING",
        MODEL_2_VERSION,
    )

    if row != expected:
        raise ControlledTrialPreparationError(
            "Created order did not match the requested "
            "controlled trial."
        )

    if pending_count != 1:
        raise ControlledTrialPreparationError(
            "Expected exactly one pending order after creation."
        )

    if fill_count != 0:
        raise ControlledTrialPreparationError(
            "A fill unexpectedly exists after order creation."
        )

    if attempt_count != 0:
        raise ControlledTrialPreparationError(
            "An execution attempt unexpectedly exists "
            "after order creation."
        )

    print("RESULT")
    print("------")
    print(
        "Controlled trial order created successfully."
    )
    print()
    print(f"Status:   PENDING")
    print(f"Fills:    {fill_count}")
    print(f"Attempts: {attempt_count}")
    print()
    print(
        "No execution occurred."
    )

    return order_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare exactly one guarded Model 2 "
            "controlled paper-trading trial order."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        type=date.fromisoformat,
        help="Future execution session YYYY-MM-DD.",
    )

    parser.add_argument(
        "--ticker",
        default="AAPL",
        help="Controlled-trial ticker. Default: AAPL.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually create the pending paper order.",
    )

    parser.add_argument(
        "--confirm",
        default="",
        help="Must equal PREPARE-MODEL2-TRIAL.",
    )

    args = parser.parse_args()

    try:
        prepare_controlled_trial(
            execution_session=args.session,
            ticker=args.ticker,
            apply=args.apply,
            confirmation=args.confirm,
        )

        return 0

    except Exception as exc:
        print()
        print(
            "MODEL 2 TRIAL PREPARATION: BLOCKED",
            file=sys.stderr,
        )
        print(
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())