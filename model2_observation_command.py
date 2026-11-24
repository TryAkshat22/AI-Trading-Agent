from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)
from model2_execution_readiness import check_execution_window
from services.intraday_collector import (
    IntradayObservationStorage,
    YahooIntradayCollector,
)
from trading.flexible_observation_selector import (
    FlexibleObservationSelector,
)
from trading.orders import OrderSide
from trading.portfolio import Portfolio


class Model2ObservationCommandError(RuntimeError):
    """Safe observation collection cannot proceed."""


@dataclass(frozen=True)
class ObservationRequirements:
    order_ids: tuple[str, ...]
    tickers: tuple[str, ...]
    holding_tickers: tuple[str, ...]


def discover_requirements(
    trading_database: str | Path,
    execution_session: date,
) -> ObservationRequirements:
    """
    Inspect pending orders and reconstruct existing holdings.

    Reads the trading database only. Never creates or
    changes trading records.
    """
    path = Path(trading_database).expanduser().resolve()

    if not path.is_file():
        raise Model2ObservationCommandError(
            "Model 2 trading database is missing."
        )

    try:
        with sqlite3.connect(
            path.as_uri() + "?mode=ro",
            uri=True,
            timeout=10,
        ) as connection:
            connection.execute("PRAGMA query_only = ON")

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
                raise Model2ObservationCommandError(
                    "Unexpected Model 2 account configuration."
                )

            portfolio = Portfolio(
                starting_cash=accounts[0][1]
            )

            # Reconstruct holdings using persisted fills.
            # A filled order from the requested session
            # may already contribute to the portfolio.
            fills = connection.execute(
                """
                SELECT
                    ticker,
                    side,
                    quantity,
                    fill_price,
                    fees
                FROM paper_fills
                ORDER BY
                    execution_session,
                    created_at_utc,
                    fill_id
                """
            ).fetchall()

            for ticker, side, quantity, price, fees in fills:
                if side == OrderSide.BUY.value:
                    portfolio.buy(
                        ticker,
                        quantity,
                        price,
                        fees,
                    )

                elif side == OrderSide.SELL.value:
                    portfolio.sell(
                        ticker,
                        quantity,
                        price,
                        fees,
                    )

                else:
                    raise Model2ObservationCommandError(
                        "Stored fill has an unknown side."
                    )

            rows = connection.execute(
                """
                SELECT
                    o.order_id,
                    o.ticker,
                    o.status,
                    o.model_version,
                    (
                        SELECT COUNT(*)
                        FROM paper_fills AS f
                        WHERE f.order_id = o.order_id
                    ) AS fill_count,
                    (
                        SELECT COUNT(*)
                        FROM order_rejections AS r
                        WHERE r.order_id = o.order_id
                    ) AS rejection_count
                FROM paper_orders AS o
                WHERE o.execution_session = ?
                ORDER BY o.ticker, o.order_id
                """,
                (execution_session.isoformat(),),
            ).fetchall()

            if not rows:
                raise Model2ObservationCommandError(
                    "No orders are scheduled for this session."
                )

            order_ids = []
            order_tickers = []

            for (
                order_id,
                ticker,
                status,
                model_version,
                fill_count,
                rejection_count,
            ) in rows:

                if model_version != MODEL_2_VERSION:
                    raise Model2ObservationCommandError(
                        "Order belongs to an unexpected model: "
                        f"{order_id}."
                    )

                # Terminal orders may share the session with
                # still-pending orders. Verify their persisted
                # records, then skip them.
                if status == "FILLED":

                    if (
                        fill_count != 1
                        or rejection_count != 0
                    ):
                        raise Model2ObservationCommandError(
                            "Filled order has inconsistent records: "
                            f"{order_id}."
                        )

                    continue

                if status == "REJECTED":

                    if (
                        fill_count != 0
                        or rejection_count < 1
                    ):
                        raise Model2ObservationCommandError(
                            "Rejected order has inconsistent records: "
                            f"{order_id}."
                        )

                    continue

                # A pending order must have no fill or
                # rejection record.
                if status == "PENDING":

                    if (
                        fill_count != 0
                        or rejection_count != 0
                    ):
                        raise Model2ObservationCommandError(
                            "Pending order has inconsistent records: "
                            f"{order_id}."
                        )

                else:
                    raise Model2ObservationCommandError(
                        "Order has an unexpected status: "
                        f"{order_id} ({status})."
                    )

                ticker = ticker.strip().upper()

                if not ticker:
                    raise Model2ObservationCommandError(
                        f"Order has a blank ticker: {order_id}."
                    )

                order_ids.append(order_id)
                order_tickers.append(ticker)

            if not order_ids:
                raise Model2ObservationCommandError(
                    "No pending orders remain for this session; "
                    "all scheduled orders are terminal and not eligible "
                    "for observation collection."
                )

            holding_tickers = tuple(
                sorted(portfolio.positions)
            )

            tickers = tuple(
                dict.fromkeys(
                    order_tickers
                    + list(holding_tickers)
                )
            )

            return ObservationRequirements(
                order_ids=tuple(order_ids),
                tickers=tickers,
                holding_tickers=holding_tickers,
            )

    except sqlite3.Error as exc:
        raise Model2ObservationCommandError(
            "Cannot inspect Model 2 trading records: "
            f"{exc}"
        ) from exc


def collect_required_observations(
    *,
    execution_session: date,
    clock: Callable[[], datetime] | None = None,
):
    """
    Collect observations only.

    Writes intraday observations to the configured
    observation database. Never writes trading data.
    """
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)

    check_execution_window(
        execution_session,
        clock(),
    )

    paths = get_model2_paths()

    model1_database = Path(
        paths.model1_database
    ).expanduser().resolve()

    trading_database = Path(
        paths.model2_database
    ).expanduser().resolve()

    observation_database = Path(
        paths.observation_database
    ).expanduser().resolve()

    if trading_database in {
        model1_database,
        observation_database,
    }:
        raise Model2ObservationCommandError(
            "Trading and observation databases "
            "are not isolated."
        )

    if not observation_database.is_file():
        raise Model2ObservationCommandError(
            "Observation database is missing."
        )

    requirements = discover_requirements(
        trading_database,
        execution_session,
    )

    # Collection can take time, so check the
    # execution window again before requesting data.
    check_execution_window(
        execution_session,
        clock(),
    )

    storage = IntradayObservationStorage(
        observation_database
    )

    # The schema must already exist.
    # Do not initialize tables here.
    collector = YahooIntradayCollector(
        storage=storage,
    )

    result = collector.collect_batch(
        requirements.tickers
    )

    returned = tuple(
        outcome.ticker
        for outcome in result.outcomes
    )

    if (
        len(returned) != len(requirements.tickers)
        or set(returned)
        != set(requirements.tickers)
        or len(set(returned))
        != len(returned)
    ):
        raise Model2ObservationCommandError(
            "Collector returned an incomplete "
            "or duplicate ticker set."
        )

    failures = [
        outcome
        for outcome in result.outcomes
        if outcome.error is not None
    ]

    if failures:
        details = "; ".join(
            f"{item.ticker}: {item.error}"
            for item in failures
        )

        raise Model2ObservationCommandError(
            "Observation collection failed: "
            + details
        )

    checked_at = clock()

    # Successful collection does not guarantee
    # that all bars remain fresh afterward.
    check_execution_window(
        execution_session,
        checked_at,
    )

    selector = FlexibleObservationSelector(
        database_path=observation_database,
    )

    selected = {}

    for ticker in requirements.tickers:
        selected[ticker] = selector.select(
            ticker=ticker,
            execution_session=execution_session,
            checked_at=checked_at,
        )

    # If trading state changed while collecting,
    # this result cannot be treated as ready.
    current = discover_requirements(
        trading_database,
        execution_session,
    )

    if current != requirements:
        raise Model2ObservationCommandError(
            "Order or holding requirements changed "
            "during collection."
        )

    return requirements, selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Model 2 observation discovery and "
            "explicit collection. Never executes trades."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        type=date.fromisoformat,
        help="NYSE session: YYYY-MM-DD.",
    )

    parser.add_argument(
        "--collect",
        action="store_true",
        help=(
            "Explicitly authorize observation collection."
        ),
    )

    args = parser.parse_args()

    try:
        paths = get_model2_paths()

        if not args.collect:
            requirements = discover_requirements(
                paths.model2_database,
                args.session,
            )

            print(
                "Model 2 observation preview — READ ONLY"
            )
            print(
                "======================================="
            )
            print(
                f"Session: {args.session}"
            )
            print(
                "Pending orders: "
                f"{len(requirements.order_ids)}"
            )
            print(
                "Tickers requiring observations: "
                + ", ".join(
                    requirements.tickers
                )
            )
            print(
                "Existing holdings: "
                + (
                    ", ".join(
                        requirements.holding_tickers
                    )
                    or "none"
                )
            )

            print()

            print(
                "No prices collected; no database "
                "changes were made."
            )

            return 0

        requirements, selected = (
            collect_required_observations(
                execution_session=args.session,
            )
        )

        print(
            "Model 2 observation collection — COMPLETE"
        )
        print(
            "========================================="
        )
        print(
            f"Session: {args.session}"
        )
        print(
            "Pending orders: "
            f"{len(requirements.order_ids)}"
        )
        print(
            "Fresh observations validated: "
            f"{len(selected)}"
        )

        for ticker in requirements.tickers:
            observation = selected[ticker]

            print(
                f"  {ticker}: "
                f"{observation.price_field} "
                f"{observation.reference_price}"
            )

        print()

        print(
            "OBSERVATIONS ONLY: No orders or fills "
            "were created or changed."
        )

        return 0

    except Exception as exc:
        print(
            "MODEL 2 OBSERVATION COMMAND: BLOCKED",
            file=sys.stderr,
        )

        print(
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        print(
            "No trading orders or fills were "
            "created by this command.",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )