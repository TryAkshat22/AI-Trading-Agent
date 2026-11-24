
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from model2_config import get_model2_paths
from services.intraday_collector import IntradayObservation
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
    FlexibleExecutionObservationValidator,
)


class Model2ExecutionProvenanceError(RuntimeError):
    """An execution observation cannot be recorded safely."""


@dataclass(frozen=True)
class Model2ExecutionProvenance:
    execution_run_id: str
    ticker: str
    source_observation_id: int
    source_database: Path
    trading_database: Path
    bar_start_utc: datetime
    retrieved_at_utc: datetime
    reference_price: float


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2ExecutionProvenanceError(
            f"{name} must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _parse_utc(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise Model2ExecutionProvenanceError(
            f"Invalid stored {name}."
        ) from exc

    return _utc(parsed, name)


def _read_source(
    database_path: Path,
    observation: FlexibleExecutionObservation,
) -> tuple[int, IntradayObservation]:
    """
    Retrieve the exact original observation from
    the research database without modifying it.
    """
    if not database_path.is_file():
        raise Model2ExecutionProvenanceError(
            "Original observation database is missing."
        )

    uri = database_path.as_uri() + "?mode=ro"

    try:
        with sqlite3.connect(
            uri,
            uri=True,
            timeout=10,
        ) as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    ticker,
                    provider,
                    bar_start_utc,
                    retrieved_at_utc,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume
                FROM intraday_observations
                WHERE ticker = ?
                  AND provider = ?
                """,
                (
                    observation.ticker,
                    observation.provider,
                ),
            ).fetchall()
    except sqlite3.Error as exc:
        raise Model2ExecutionProvenanceError(
            "Unable to read original intraday observations."
        ) from exc

    matching = []

    for item in row:
        bar_start = _parse_utc(
            item[3],
            "bar_start_utc",
        )
        retrieved = _parse_utc(
            item[4],
            "retrieved_at_utc",
        )

        if (
            bar_start == observation.bar_start_utc
            and retrieved == observation.retrieved_at_utc
        ):
            matching.append(
                (
                    item[0],
                    IntradayObservation(
                        ticker=item[1],
                        provider=item[2],
                        bar_start_utc=bar_start,
                        retrieved_at_utc=retrieved,
                        open=item[5],
                        high=item[6],
                        low=item[7],
                        close=item[8],
                        volume=item[9],
                    ),
                )
            )

    if len(matching) != 1:
        raise Model2ExecutionProvenanceError(
            "The validated observation does not match "
            "exactly one original stored observation."
        )

    return matching[0]


def record_model2_execution_observation(
    observation: FlexibleExecutionObservation,
    *,
    now: datetime | None = None,
) -> Model2ExecutionProvenance:
    """
    Record one independently verifiable intraday
    execution-data event in Model 2.

    Does not create orders, attempts, fills,
    rejections, or portfolio snapshots.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    recorded_at = _utc(now, "now")
    original_checked_at = _utc(
        observation.execution_checked_at_utc,
        "execution_checked_at_utc",
    )

    if original_checked_at > recorded_at:
        raise Model2ExecutionProvenanceError(
            "Original check time is in the future."
        )

    paths = get_model2_paths()
    source_database = paths.observation_database.resolve()
    trading_database = paths.model2_database.resolve()

    if source_database == trading_database:
        raise Model2ExecutionProvenanceError(
            "Observation and trading databases must differ."
        )

    if not trading_database.is_file():
        raise Model2ExecutionProvenanceError(
            "Model 2 trading database is missing."
        )

    source_id, source = _read_source(
        source_database,
        observation,
    )

    # Revalidate the ORIGINAL stored values at the
    # current time. A once-valid bar can become stale.
    validated_now = (
        FlexibleExecutionObservationValidator()
        .validate(
            observation=source,
            execution_session=observation.execution_session,
            checked_at=recorded_at,
            expected_ticker=observation.ticker,
        )
    )

    if (
        validated_now.reference_price
        != observation.reference_price
        or validated_now.price_field
        != observation.price_field
        or validated_now.model
        != observation.model
        or validated_now.bar_start_utc
        != observation.bar_start_utc
        or validated_now.bar_end_utc
        != observation.bar_end_utc
        or validated_now.provider
        != observation.provider
    ):
        raise Model2ExecutionProvenanceError(
            "Validated price or provenance differs "
            "from the original stored observation."
        )

    prices = (
        source.open,
        source.high,
        source.low,
        source.close,
    )

    try:
        numeric_prices = tuple(
            float(value)
            for value in prices
        )
        volume = float(source.volume)
    except (TypeError, ValueError) as exc:
        raise Model2ExecutionProvenanceError(
            "Source OHLCV is not numeric."
        ) from exc

    if (
        any(
            not math.isfinite(price) or price <= 0
            for price in numeric_prices
        )
        or not math.isfinite(volume)
        or volume < 0
    ):
        raise Model2ExecutionProvenanceError(
            "Source OHLCV contains invalid values."
        )

    opened, high, low, closed = numeric_prices

    if (
        high < max(opened, low, closed)
        or low > min(opened, high, closed)
    ):
        raise Model2ExecutionProvenanceError(
            "Source OHLC prices are inconsistent."
        )

    run_id = str(uuid4())
    session_text = observation.execution_session.isoformat()
    source_path_text = str(source_database)

    # mode=rw refuses to create a missing database.
    uri = trading_database.as_uri() + "?mode=rw"

    try:
        with sqlite3.connect(
            uri,
            uri=True,
            timeout=10,
        ) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")

            account_rows = connection.execute(
                "SELECT account_id FROM paper_accounts"
            ).fetchall()

            if account_rows != [("model2-paper",)]:
                raise Model2ExecutionProvenanceError(
                    "Unexpected Model 2 account configuration."
                )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS
                model2_execution_observation_lineage (
                    execution_run_id TEXT PRIMARY KEY,
                    source_database TEXT NOT NULL,
                    source_observation_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    execution_session TEXT NOT NULL,
                    bar_start_utc TEXT NOT NULL,
                    bar_end_utc TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL,
                    validated_at_utc TEXT NOT NULL,
                    price_field TEXT NOT NULL,
                    reference_price REAL NOT NULL,
                    open_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    close_price REAL NOT NULL,
                    volume REAL NOT NULL,
                    observation_model TEXT NOT NULL,
                    FOREIGN KEY (execution_run_id)
                        REFERENCES ingestion_runs(run_id),
                    UNIQUE (
                        source_database,
                        source_observation_id
                    )
                )
                """
            )

                        # The same observed bar may support more
            # than one order. Reuse its existing run,
            # but only if its recorded provenance
            # matches the original observation exactly.
            existing = connection.execute(
                """
                SELECT
                    l.execution_run_id,
                    l.ticker,
                    l.provider,
                    l.execution_session,
                    l.bar_start_utc,
                    l.bar_end_utc,
                    l.retrieved_at_utc,
                    l.price_field,
                    l.reference_price,
                    l.open_price,
                    l.high_price,
                    l.low_price,
                    l.close_price,
                    l.volume,
                    l.observation_model,
                    i.ticker,
                    i.provider,
                    i.retrieved_at_utc,
                    i.safe_to_use
                FROM model2_execution_observation_lineage AS l
                JOIN ingestion_runs AS i
                    ON i.run_id = l.execution_run_id
                WHERE l.source_database = ?
                  AND l.source_observation_id = ?
                """,
                (
                    source_path_text,
                    source_id,
                ),
            ).fetchone()

            if existing is not None:
                expected = (
                    observation.ticker,
                    observation.provider,
                    session_text,
                    source.bar_start_utc.isoformat(),
                    observation.bar_end_utc.isoformat(),
                    source.retrieved_at_utc.isoformat(),
                    observation.price_field,
                    observation.reference_price,
                    opened,
                    high,
                    low,
                    closed,
                    volume,
                    observation.model,
                    observation.ticker,
                    observation.provider,
                    source.retrieved_at_utc.isoformat(),
                    1,
                )

                if tuple(existing[1:]) != expected:
                    raise Model2ExecutionProvenanceError(
                        "An existing execution run has "
                        "inconsistent observation provenance."
                    )

                return Model2ExecutionProvenance(
                    execution_run_id=existing[0],
                    ticker=observation.ticker,
                    source_observation_id=source_id,
                    source_database=source_database,
                    trading_database=trading_database,
                    bar_start_utc=source.bar_start_utc,
                    retrieved_at_utc=source.retrieved_at_utc,
                    reference_price=observation.reference_price,
                )

            # This ingestion run is the parent ID
            # required by the existing attempt/fill
            # lineage tables. The dedicated lineage
            # table preserves the minute-level detail.
            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    run_id,
                    ticker,
                    provider,
                    retrieved_at_utc,
                    checked_at_utc,
                    latest_data_session,
                    latest_expected_session,
                    safe_to_use,
                    issue_count,
                    issues_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                """,
                (
                    run_id,
                    observation.ticker,
                    observation.provider,
                    source.retrieved_at_utc.isoformat(),
                    recorded_at.isoformat(),
                    session_text,
                    session_text,
                    json.dumps([]),
                ),
            )

            connection.execute(
                """
                INSERT INTO
                model2_execution_observation_lineage (
                    execution_run_id,
                    source_database,
                    source_observation_id,
                    ticker,
                    provider,
                    execution_session,
                    bar_start_utc,
                    bar_end_utc,
                    retrieved_at_utc,
                    validated_at_utc,
                    price_field,
                    reference_price,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    observation_model
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    source_path_text,
                    source_id,
                    observation.ticker,
                    observation.provider,
                    session_text,
                    source.bar_start_utc.isoformat(),
                    observation.bar_end_utc.isoformat(),
                    source.retrieved_at_utc.isoformat(),
                    recorded_at.isoformat(),
                    observation.price_field,
                    observation.reference_price,
                    opened,
                    high,
                    low,
                    closed,
                    volume,
                    observation.model,
                ),
            )

    except sqlite3.IntegrityError as exc:
        raise Model2ExecutionProvenanceError(
            "Execution observation already recorded, "
            "or its database lineage is invalid."
        ) from exc
    except sqlite3.Error as exc:
        raise Model2ExecutionProvenanceError(
            "Could not persist execution observation."
        ) from exc

    return Model2ExecutionProvenance(
        execution_run_id=run_id,
        ticker=observation.ticker,
        source_observation_id=source_id,
        source_database=source_database,
        trading_database=trading_database,
        bar_start_utc=source.bar_start_utc,
        retrieved_at_utc=source.retrieved_at_utc,
        reference_price=observation.reference_price,
    )