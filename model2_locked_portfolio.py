
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)
from trading.orders import OrderSide
from trading.portfolio import Portfolio, PortfolioError


class Model2LockedPortfolioError(RuntimeError):
    """A locked portfolio cannot be reconstructed safely."""


def _test_database_path(database_path: str | Path) -> Path:
    path = Path(database_path).expanduser().resolve()

    paths = get_model2_paths()
    protected = {
        Path(paths.model1_database).expanduser().resolve(),
        Path(paths.model2_database).expanduser().resolve(),
        Path(paths.observation_database).expanduser().resolve(),
    }

    if path in protected:
        raise Model2LockedPortfolioError(
            "This test-only component cannot access a "
            "configured live database."
        )

    if not path.is_file():
        raise Model2LockedPortfolioError(
            "Temporary trading database does not exist."
        )

    return path


def _rebuild_with_connection(
    connection: sqlite3.Connection,
) -> Portfolio:
    accounts = connection.execute(
        """
        SELECT account_id, starting_cash
        FROM paper_accounts
        """
    ).fetchall()

    if (
        len(accounts) != 1
        or accounts[0][0] != MODEL_2_ACCOUNT_ID
    ):
        raise Model2LockedPortfolioError(
            "Unexpected Model 2 account configuration."
        )

    try:
        portfolio = Portfolio(
            starting_cash=Decimal(str(accounts[0][1]))
        )
    except (ValueError, ArithmeticError) as exc:
        raise Model2LockedPortfolioError(
            "Starting cash is invalid."
        ) from exc

    # These are the same deterministic replay-order
    # fields used by TradingStorage.list_fills().
    rows = connection.execute(
        """
        SELECT
            f.fill_id,
            f.order_id,
            f.ticker,
            f.side,
            f.quantity,
            f.fill_price,
            f.fees,
            f.execution_session,
            o.ticker,
            o.side,
            o.quantity,
            o.execution_session,
            o.status,
            o.model_version
        FROM paper_fills AS f
        LEFT JOIN paper_orders AS o
            ON o.order_id = f.order_id
        ORDER BY
            f.execution_session,
            f.created_at_utc,
            f.fill_id
        """
    ).fetchall()

    seen_orders: set[str] = set()

    for row in rows:
        (
            fill_id,
            order_id,
            ticker,
            side,
            quantity,
            price,
            fees,
            fill_session,
            order_ticker,
            order_side,
            order_quantity,
            order_session,
            order_status,
            model_version,
        ) = row

        if (
            order_id in seen_orders
            or order_ticker is None
            or ticker != order_ticker
            or side != order_side
            or quantity != order_quantity
            or fill_session != order_session
            or order_status != "FILLED"
            or model_version != MODEL_2_VERSION
        ):
            raise Model2LockedPortfolioError(
                "Fill and order records are inconsistent: "
                f"{fill_id}"
            )

        seen_orders.add(order_id)

        try:
            if side == OrderSide.BUY.value:
                portfolio.buy(
                    ticker=ticker,
                    quantity=quantity,
                    price=Decimal(str(price)),
                    fees=Decimal(str(fees)),
                )

            elif side == OrderSide.SELL.value:
                portfolio.sell(
                    ticker=ticker,
                    quantity=quantity,
                    price=Decimal(str(price)),
                    fees=Decimal(str(fees)),
                )

            else:
                raise Model2LockedPortfolioError(
                    f"Unsupported fill side: {side}"
                )

        except (
            PortfolioError,
            ValueError,
            ArithmeticError,
        ) as exc:
            raise Model2LockedPortfolioError(
                f"Cannot replay fill {fill_id}: {exc}"
            ) from exc

    return portfolio


@contextmanager
def locked_test_model2_portfolio(
    database_path: str | Path,
) -> Iterator[tuple[sqlite3.Connection, Portfolio]]:
    """
    TEST-ONLY locked portfolio reconstruction.

    Acquires BEGIN IMMEDIATE before reading account
    or fills, and always rolls back on exit.

    It creates no fills, orders, attempts, or snapshots.
    A later integrated executor will need to own this
    transaction through its risk check and fill commit.
    """
    path = _test_database_path(database_path)

    connection = sqlite3.connect(
        path.as_uri() + "?mode=rw",
        uri=True,
        timeout=5,
        isolation_level=None,
    )

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")

        portfolio = _rebuild_with_connection(
            connection
        )

        yield connection, portfolio

    except sqlite3.Error as exc:
        raise Model2LockedPortfolioError(
            f"Locked portfolio operation failed: {exc}"
        ) from exc

    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

        connection.close()