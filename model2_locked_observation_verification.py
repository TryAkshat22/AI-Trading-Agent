
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from model2_config import get_model2_paths
from services.intraday_collector import IntradayObservation
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
    FlexibleExecutionObservationError,
    FlexibleExecutionObservationValidator,
)


class Model2ObservationVerificationError(RuntimeError):
    """Execution-price provenance could not be verified."""


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2ObservationVerificationError(
            f"{name} must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _stored_time(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise Model2ObservationVerificationError(
            f"Invalid stored {name}."
        ) from exc

    return _utc(parsed, name)


def verify_locked_model2_observation(
    *,
    connection: sqlite3.Connection,
    source_database: str | Path,
    observation: FlexibleExecutionObservation,
    now: datetime,
) -> str:
    """
    Verify a proposed execution observation against:

      1. The original stored intraday bar.
      2. Model 2's execution-observation lineage.
      3. Its parent ingestion run.
      4. The execution validator at the actual check time.

    Returns the authentic execution_run_id.

    The caller must already hold a write transaction
    on a TEMPORARY Model 2 trading database.

    This function does not insert or update anything.
    """
    if not connection.in_transaction:
        raise Model2ObservationVerificationError(
            "A database transaction is required."
        )

    checked_now = _utc(now, "now")

    paths = get_model2_paths()

    protected_trading = Path(
        paths.model2_database
    ).expanduser().resolve()

    expected_source = Path(
        paths.observation_database
    ).expanduser().resolve()

    supplied_source = Path(
        source_database
    ).expanduser().resolve()

    # This module is for controlled integration tests.
    # Never use it to inspect the configured live
    # Model 2 trading database.
    attached_databases = connection.execute(
        "PRAGMA database_list"
    ).fetchall()

    main_paths = [
        Path(row[2]).resolve()
        for row in attached_databases
        if row[1] == "main" and row[2]
    ]

    if (
        len(main_paths) != 1
        or main_paths[0] == protected_trading
        or main_paths[0] == expected_source
    ):
        raise Model2ObservationVerificationError(
            "Expected an isolated temporary "
            "Model 2 trading database."
        )

    if supplied_source != expected_source:
        raise Model2ObservationVerificationError(
            "Source database differs from the "
            "configured observation database."
        )

    if (
        supplied_source == main_paths[0]
        or not supplied_source.is_file()
    ):
        raise Model2ObservationVerificationError(
            "Original observation database is missing "
            "or is not separate from trading."
        )

    original_check = _utc(
        observation.execution_checked_at_utc,
        "execution_checked_at_utc",
    )

    if original_check > checked_now:
        raise Model2ObservationVerificationError(
            "Observation check time is in the future."
        )

    # Read the original source without creating or
    # modifying its database.
    source_uri = supplied_source.as_uri() + "?mode=ro"

    try:
        with sqlite3.connect(
            source_uri,
            uri=True,
            timeout=10,
        ) as source_connection:
            source_connection.execute(
                "PRAGMA query_only = ON"
            )

            source_rows = source_connection.execute(
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
        raise Model2ObservationVerificationError(
            "Could not read the original observation."
        ) from exc

    matches = []

    for row in source_rows:
        bar_start = _stored_time(
            row[3],
            "bar_start_utc",
        )
        retrieved = _stored_time(
            row[4],
            "retrieved_at_utc",
        )

        if (
            bar_start
            == _utc(
                observation.bar_start_utc,
                "bar_start_utc",
            )
            and retrieved
            == _utc(
                observation.retrieved_at_utc,
                "retrieved_at_utc",
            )
        ):
            matches.append(
                (
                    row[0],
                    IntradayObservation(
                        ticker=row[1],
                        provider=row[2],
                        bar_start_utc=bar_start,
                        retrieved_at_utc=retrieved,
                        open=row[5],
                        high=row[6],
                        low=row[7],
                        close=row[8],
                        volume=row[9],
                    ),
                )
            )

    if len(matches) != 1:
        raise Model2ObservationVerificationError(
            "The proposed observation does not match "
            "exactly one original stored bar."
        )

    source_id, source = matches[0]

    validator = FlexibleExecutionObservationValidator()

    try:
        validated_at_original_check = validator.validate(
            observation=source,
            execution_session=observation.execution_session,
            checked_at=original_check,
            expected_ticker=observation.ticker,
        )

        validated_now = validator.validate(
            observation=source,
            execution_session=observation.execution_session,
            checked_at=checked_now,
            expected_ticker=observation.ticker,
        )

    except FlexibleExecutionObservationError as exc:
        raise Model2ObservationVerificationError(
            f"Observation is invalid or stale: {exc}"
        ) from exc

    # A caller cannot change the price, provider,
    # original timestamps, price field, or model.
    if validated_at_original_check != observation:
        raise Model2ObservationVerificationError(
            "Proposed observation differs from "
            "the original validated bar."
        )

    try:
        lineage_rows = connection.execute(
            """
            SELECT
                l.execution_run_id,
                l.ticker,
                l.provider,
                l.execution_session,
                l.bar_start_utc,
                l.bar_end_utc,
                l.retrieved_at_utc,
                l.validated_at_utc,
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
                str(supplied_source),
                source_id,
            ),
        ).fetchall()

    except sqlite3.Error as exc:
        raise Model2ObservationVerificationError(
            "Could not read execution-data lineage."
        ) from exc

    if len(lineage_rows) != 1:
        raise Model2ObservationVerificationError(
            "Exactly one matching Model 2 execution "
            "lineage record is required."
        )

    row = lineage_rows[0]

    (
        execution_run_id,
        lineage_ticker,
        lineage_provider,
        lineage_session,
        lineage_bar_start,
        lineage_bar_end,
        lineage_retrieved,
        lineage_validated,
        lineage_field,
        lineage_reference,
        lineage_open,
        lineage_high,
        lineage_low,
        lineage_close,
        lineage_volume,
        lineage_model,
        run_ticker,
        run_provider,
        run_retrieved,
        run_safe,
    ) = row

    expected_values = (
        observation.ticker,
        source.provider,
        observation.execution_session.isoformat(),
        source.bar_start_utc,
        validated_now.bar_end_utc,
        source.retrieved_at_utc,
        observation.price_field,
        observation.reference_price,
        source.open,
        source.high,
        source.low,
        source.close,
        source.volume,
        observation.model,
        observation.ticker,
        source.provider,
        source.retrieved_at_utc,
        1,
    )

    actual_values = (
        lineage_ticker,
        lineage_provider,
        lineage_session,
        _stored_time(
            lineage_bar_start,
            "lineage bar start",
        ),
        _stored_time(
            lineage_bar_end,
            "lineage bar end",
        ),
        _stored_time(
            lineage_retrieved,
            "lineage retrieval",
        ),
        lineage_field,
        lineage_reference,
        lineage_open,
        lineage_high,
        lineage_low,
        lineage_close,
        lineage_volume,
        lineage_model,
        run_ticker,
        run_provider,
        _stored_time(
            run_retrieved,
            "ingestion retrieval",
        ),
        run_safe,
    )

    if actual_values != expected_values:
        raise Model2ObservationVerificationError(
            "Model 2 lineage differs from "
            "the original intraday observation."
        )

    validated_at = _stored_time(
        lineage_validated,
        "lineage validation time",
    )

    if not (
        source.retrieved_at_utc
        <= original_check
        <= validated_at
        <= checked_now
    ):
        raise Model2ObservationVerificationError(
            "Execution-data validation timestamps "
            "are inconsistent."
        )

    if not execution_run_id:
        raise Model2ObservationVerificationError(
            "Execution run ID is missing."
        )

    return execution_run_id