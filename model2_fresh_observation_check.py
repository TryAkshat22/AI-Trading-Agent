
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from database.pending_order_query import PendingOrderQuery
from model2_config import (
    MODEL_2_VERSION,
    get_model2_paths,
)
from model2_execution_readiness import check_execution_window
from services.intraday_collector import (
    CollectionBatchResult,
    IntradayObservationStorage,
    YahooIntradayCollector,
)
from trading.flexible_observation_selector import (
    FlexibleObservationSelector,
)
from trading.flexible_order_eligibility import (
    FlexibleOrderEligibilityChecker,
    FlexibleEligibilityResult,
)


class Model2FreshObservationError(RuntimeError):
    """A fresh Model 2 execution check cannot proceed."""


@dataclass(frozen=True)
class Model2FreshObservationResult:
    execution_session: date
    collection: CollectionBatchResult | None
    eligibility: FlexibleEligibilityResult | None
    pending_order_count: int

    @property
    def ready_order_count(self) -> int:
        if self.eligibility is None:
            return 0
        return self.eligibility.eligible_count


def collect_and_check_model2(
    execution_session: date,
    *,
    clock: Callable[[], datetime] | None = None,
    collector_factory=None,
    pending_query_factory=None,
    checker_factory=None,
) -> Model2FreshObservationResult:
    """
    Collect fresh observations, then inspect Model 2 orders.

    Writes only to the observation database.

    Does not create execution attempts, orders, fills,
    rejections, or portfolio snapshots.

    Dependency factories permit isolated tests without
    downloading real market data.
    """

    if clock is None:
        clock = lambda: datetime.now(timezone.utc)

    # Check the real execution window before doing work.
    started_at = clock()
    check_execution_window(execution_session, started_at)

    paths = get_model2_paths()

    trading_database = Path(
        paths.model2_database
    ).resolve()

    observation_database = Path(
        paths.observation_database
    ).resolve()

    if trading_database == observation_database:
        raise Model2FreshObservationError(
            "Trading and observation databases "
            "must be separate."
        )

    if not trading_database.is_file():
        raise Model2FreshObservationError(
            "Model 2 trading database is missing."
        )

    if not observation_database.is_file():
        raise Model2FreshObservationError(
            "Intraday observation database is missing."
        )

    # Discover ONLY orders due for the requested session
    # in Model 2's database.
    if pending_query_factory is None:
        pending_query = PendingOrderQuery(
            trading_database
        )
    else:
        pending_query = pending_query_factory(
            trading_database
        )

    pending_orders = pending_query.find_for_session(
        execution_session
    )

    if not pending_orders:
        return Model2FreshObservationResult(
            execution_session=execution_session,
            collection=None,
            eligibility=None,
            pending_order_count=0,
        )

    # Never use this collector to advance orders
    # belonging to a different execution model.
    unexpected = [
        order.order_id
        for order in pending_orders
        if order.model_version != MODEL_2_VERSION
    ]

    if unexpected:
        raise Model2FreshObservationError(
            "Model 2 database contains pending orders "
            "from an unexpected model. "
            f"First order: {unexpected[0]}"
        )

    tickers = tuple(
        dict.fromkeys(
            order.ticker.strip().upper()
            for order in pending_orders
        )
    )

    if any(not ticker for ticker in tickers):
        raise Model2FreshObservationError(
            "A pending order has an empty ticker."
        )

    # This storage is deliberately pointed at the
    # ORIGINAL observation database, not Model 2's
    # trading database.
    observation_storage = IntradayObservationStorage(
        observation_database
    )

    observation_storage.initialize()

    if collector_factory is None:
        collector = YahooIntradayCollector(
            storage=observation_storage
        )
    else:
        collector = collector_factory(
            observation_storage
        )

    collection = collector.collect_batch(tickers)

    # A failed ticker cannot be silently dropped from
    # a supposedly ready execution batch.
    failed = [
        outcome
        for outcome in collection.outcomes
        if outcome.error is not None
    ]

    returned_tickers = tuple(
        outcome.ticker
        for outcome in collection.outcomes
    )

    if (
        len(returned_tickers) != len(tickers)
        or set(returned_tickers) != set(tickers)
        or len(set(returned_tickers)) != len(returned_tickers)
    ):
        raise Model2FreshObservationError(
            "Collector did not return exactly one "
            "outcome per requested ticker."
        )

    if failed:
        details = "; ".join(
            f"{outcome.ticker}: {outcome.error}"
            for outcome in failed
        )

        raise Model2FreshObservationError(
            "Fresh observation collection failed. "
            f"No execution batch was approved. {details}"
        )

    # Use the time AFTER collection, never its start
    # time, when validating observation freshness.
    checked_at = clock()
    check_execution_window(
        execution_session,
        checked_at,
    )

    selector = FlexibleObservationSelector(
        database_path=observation_database
    )

    if checker_factory is None:
        checker = FlexibleOrderEligibilityChecker(
            database_path=trading_database,
            observation_selector=selector,
            expected_model_version=MODEL_2_VERSION,
        )
    else:
        checker = checker_factory(
            trading_database,
            selector,
        )

    eligibility = checker.check(
        execution_session=execution_session,
        checked_at=checked_at,
    )

    return Model2FreshObservationResult(
        execution_session=execution_session,
        collection=collection,
        eligibility=eligibility,
        pending_order_count=len(pending_orders),
    )