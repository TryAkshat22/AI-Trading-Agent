from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


ZERO = Decimal("0")


@dataclass
class Lot:
    quantity: int
    price: Decimal


@dataclass
class Position:
    ticker: str
    quantity: int
    average_cost: Decimal
    cost_basis: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def percent(value: Decimal) -> str:
    return f"{value:.2f}%"


def decimal_value(value) -> Decimal:
    return Decimal(str(value))


def load_starting_cash(
    model2_db: Path,
) -> Decimal:
    with sqlite3.connect(
        model2_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        row = connection.execute(
            """
            SELECT starting_cash
            FROM paper_accounts
            WHERE account_id = ?
            """,
            (MODEL_2_ACCOUNT_ID,),
        ).fetchone()

    if row is None:
        raise RuntimeError(
            "Model 2 account was not found."
        )

    return decimal_value(row[0])


def load_fills(
    model2_db: Path,
):
    with sqlite3.connect(
        model2_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(paper_fills)"
            ).fetchall()
        }

        required = {
            "fill_id",
            "order_id",
            "ticker",
            "side",
            "quantity",
            "fill_price",
            "created_at_utc",
        }

        missing = required - columns

        if missing:
            raise RuntimeError(
                "paper_fills is missing required "
                "column(s): "
                + ", ".join(sorted(missing))
            )

        rows = connection.execute(
            """
            SELECT
                fill_id,
                order_id,
                ticker,
                side,
                quantity,
                fill_price,
                created_at_utc
            FROM paper_fills
            ORDER BY created_at_utc, fill_id
            """
        ).fetchall()

    return rows


def latest_intraday_price(
    observation_db: Path,
    ticker: str,
):
    with sqlite3.connect(
        observation_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        row = connection.execute(
            """
            SELECT
                close_price,
                bar_start_utc,
                retrieved_at_utc
            FROM intraday_observations
            WHERE ticker = ?
            ORDER BY bar_start_utc DESC,
                     retrieved_at_utc DESC
            LIMIT 1
            """,
            (ticker,),
        ).fetchone()

    if row is None:
        return None

    return (
        decimal_value(row[0]),
        row[1],
        "intraday",
    )


def latest_daily_price(
    observation_db: Path,
    ticker: str,
):
    with sqlite3.connect(
        observation_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        row = connection.execute(
            """
            SELECT
                close,
                session_date
            FROM market_bars
            WHERE ticker = ?
            ORDER BY session_date DESC, id DESC
            LIMIT 1
            """,
            (ticker,),
        ).fetchone()

    if row is None:
        return None

    return (
        decimal_value(row[0]),
        str(row[1]),
        "daily",
    )


def latest_price(
    observation_db: Path,
    ticker: str,
):
    price = latest_intraday_price(
        observation_db,
        ticker,
    )

    if price is not None:
        return price

    price = latest_daily_price(
        observation_db,
        ticker,
    )

    if price is not None:
        return price

    raise RuntimeError(
        f"No valuation price is available for {ticker}."
    )


def build_portfolio(
    fills,
    starting_cash: Decimal,
):
    lots: dict[str, deque[Lot]] = defaultdict(
        deque
    )

    cash = starting_cash
    realized_pnl = ZERO

    filled_buys = 0
    filled_sells = 0

    for (
        fill_id,
        order_id,
        ticker,
        side,
        quantity,
        fill_price,
        created_at_utc,
    ) in fills:
        ticker = ticker.upper()
        side = side.upper()

        quantity = int(quantity)
        price = decimal_value(fill_price)

        if quantity <= 0:
            raise RuntimeError(
                f"Invalid fill quantity: {fill_id}"
            )

        if price <= ZERO:
            raise RuntimeError(
                f"Invalid fill price: {fill_id}"
            )

        if side == "BUY":
            cash -= (
                Decimal(quantity) * price
            )

            lots[ticker].append(
                Lot(
                    quantity=quantity,
                    price=price,
                )
            )

            filled_buys += 1

        elif side == "SELL":
            sell_quantity = quantity

            available = sum(
                lot.quantity
                for lot in lots[ticker]
            )

            if sell_quantity > available:
                raise RuntimeError(
                    "SELL fill exceeds known Model 2 "
                    f"position for {ticker}."
                )

            cash += (
                Decimal(quantity) * price
            )

            remaining = sell_quantity

            while remaining > 0:
                lot = lots[ticker][0]

                used = min(
                    remaining,
                    lot.quantity,
                )

                realized_pnl += (
                    Decimal(used)
                    * (price - lot.price)
                )

                lot.quantity -= used
                remaining -= used

                if lot.quantity == 0:
                    lots[ticker].popleft()

            filled_sells += 1

        else:
            raise RuntimeError(
                f"Unsupported fill side: {side}"
            )

    return (
        cash,
        realized_pnl,
        lots,
        filled_buys,
        filled_sells,
    )


def load_order_statistics(
    model2_db: Path,
):
    with sqlite3.connect(
        model2_db.as_uri() + "?mode=ro",
        uri=True,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        rows = connection.execute(
            """
            SELECT status, COUNT(*)
            FROM paper_orders
            WHERE model_version = ?
            GROUP BY status
            """,
            (MODEL_2_VERSION,),
        ).fetchall()

    return {
        status: count
        for status, count in rows
    }


def main() -> int:
    paths = get_model2_paths()

    model2_db = Path(
        paths.model2_database
    ).expanduser().resolve()

    observation_db = Path(
        paths.observation_database
    ).expanduser().resolve()

    if not model2_db.is_file():
        raise RuntimeError(
            "Model 2 database does not exist."
        )

    if not observation_db.is_file():
        raise RuntimeError(
            "Observation database does not exist."
        )

    starting_cash = load_starting_cash(
        model2_db
    )

    fills = load_fills(
        model2_db
    )

    (
        cash,
        realized_pnl,
        lots,
        filled_buys,
        filled_sells,
    ) = build_portfolio(
        fills,
        starting_cash,
    )

    positions: list[Position] = []

    valuation_sources = []

    for ticker in sorted(lots):
        open_lots = [
            lot
            for lot in lots[ticker]
            if lot.quantity > 0
        ]

        if not open_lots:
            continue

        quantity = sum(
            lot.quantity
            for lot in open_lots
        )

        cost_basis = sum(
            Decimal(lot.quantity)
            * lot.price
            for lot in open_lots
        )

        average_cost = (
            cost_basis
            / Decimal(quantity)
        )

        (
            current_price,
            price_time,
            source,
        ) = latest_price(
            observation_db,
            ticker,
        )

        market_value = (
            Decimal(quantity)
            * current_price
        )

        unrealized_pnl = (
            market_value
            - cost_basis
        )

        positions.append(
            Position(
                ticker=ticker,
                quantity=quantity,
                average_cost=average_cost,
                cost_basis=cost_basis,
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
            )
        )

        valuation_sources.append(
            (
                ticker,
                source,
                price_time,
            )
        )

    market_value = sum(
        (
            position.market_value
            for position in positions
        ),
        ZERO,
    )

    unrealized_pnl = sum(
        (
            position.unrealized_pnl
            for position in positions
        ),
        ZERO,
    )

    total_equity = (
        cash
        + market_value
    )

    total_pnl = (
        total_equity
        - starting_cash
    )

    if starting_cash == ZERO:
        total_return_pct = ZERO
    else:
        total_return_pct = (
            total_pnl
            / starting_cash
            * Decimal("100")
        )

    if total_equity == ZERO:
        exposure_pct = ZERO
    else:
        exposure_pct = (
            market_value
            / total_equity
            * Decimal("100")
        )

    order_stats = load_order_statistics(
        model2_db
    )

    print()
    print("MODEL 2 PERFORMANCE")
    print("===================")
    print(
        "Read-only portfolio valuation"
    )
    print()

    print("PORTFOLIO")
    print("---------")
    print(
        f"Starting capital:   "
        f"{money(starting_cash)}"
    )
    print(
        f"Cash:               "
        f"{money(cash)}"
    )
    print(
        f"Market value:       "
        f"{money(market_value)}"
    )
    print(
        f"Total equity:       "
        f"{money(total_equity)}"
    )
    print()

    print("PERFORMANCE")
    print("-----------")
    print(
        f"Realized P/L:       "
        f"{money(realized_pnl)}"
    )
    print(
        f"Unrealized P/L:     "
        f"{money(unrealized_pnl)}"
    )
    print(
        f"Total P/L:          "
        f"{money(total_pnl)}"
    )
    print(
        f"Total return:       "
        f"{percent(total_return_pct)}"
    )
    print(
        f"Market exposure:    "
        f"{percent(exposure_pct)}"
    )
    print()

    print("OPEN POSITIONS")
    print("--------------")

    if not positions:
        print("None")
    else:
        for position in positions:
            if position.cost_basis == ZERO:
                position_return = ZERO
            else:
                position_return = (
                    position.unrealized_pnl
                    / position.cost_basis
                    * Decimal("100")
                )

            print(
                f"{position.ticker:<6} "
                f"{position.quantity:>4} shares"
            )

            print(
                f"       Average cost: "
                f"{money(position.average_cost)}"
            )

            print(
                f"       Current price: "
                f"{money(position.current_price)}"
            )

            print(
                f"       Cost basis:    "
                f"{money(position.cost_basis)}"
            )

            print(
                f"       Market value:  "
                f"{money(position.market_value)}"
            )

            print(
                f"       P/L:           "
                f"{money(position.unrealized_pnl)} "
                f"({percent(position_return)})"
            )

    print()
    print("ORDER / TRADE STATISTICS")
    print("------------------------")
    print(
        f"Filled orders:       "
        f"{order_stats.get('FILLED', 0)}"
    )
    print(
        f"Rejected orders:     "
        f"{order_stats.get('REJECTED', 0)}"
    )
    print(
        f"Pending orders:      "
        f"{order_stats.get('PENDING', 0)}"
    )
    print(
        f"BUY fills:           "
        f"{filled_buys}"
    )
    print(
        f"SELL fills:          "
        f"{filled_sells}"
    )
    print(
        f"Open positions:      "
        f"{len(positions)}"
    )

    print()
    print("VALUATION SOURCES")
    print("-----------------")

    for (
        ticker,
        source,
        price_time,
    ) in valuation_sources:
        print(
            f"{ticker}: {source} "
            f"| {price_time}"
        )

    print()
    print(
        "Report generated: "
        + datetime.now(
            timezone.utc
        ).isoformat()
    )

    print()
    print(
        "No database changes were made."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())