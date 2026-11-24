from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from model2_config import get_model2_paths


NEW_YORK = ZoneInfo("America/New_York")


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        raise ValueError(
            f"Stored datetime is timezone-naive: {value}"
        )

    return parsed.astimezone(timezone.utc)


def main() -> int:
    paths = get_model2_paths()

    observation_db = Path(
        paths.observation_database
    ).expanduser().resolve()

    print()
    print("INTRADAY COLLECTOR HEALTH")
    print("=========================")
    print("READ ONLY")
    print()
    print(f"Observation DB: {observation_db}")
    print()

    if not observation_db.is_file():
        print("RESULT: BLOCKED")
        print("Observation database does not exist.")
        return 1

    now_utc = datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NEW_YORK)
    today_ny = now_ny.date()

    print(f"Current NY time: {now_ny.isoformat()}")
    print(f"NY session date: {today_ny}")
    print()

    uri = observation_db.as_uri() + "?mode=ro"

    with sqlite3.connect(
        uri,
        uri=True,
        timeout=10,
    ) as connection:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'intraday_observations'
            """
        ).fetchone()

        if table is None:
            print("RESULT: BLOCKED")
            print(
                "intraday_observations table is missing."
            )
            return 1

        total = connection.execute(
            """
            SELECT COUNT(*)
            FROM intraday_observations
            """
        ).fetchone()[0]

        print(f"Total stored observations: {total}")
        print()

        rows = connection.execute(
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
            ORDER BY retrieved_at_utc DESC
            LIMIT 100
            """
        ).fetchall()

    if not rows:
        print("RESULT: NO DATA")
        print(
            "The observation table exists but "
            "contains no observations."
        )
        return 1

    today_rows = []

    for row in rows:
        retrieved = parse_datetime(
            row[4]
        )

        retrieved_ny = retrieved.astimezone(
            NEW_YORK
        )

        if retrieved_ny.date() == today_ny:
            today_rows.append(
                (
                    row,
                    retrieved,
                    retrieved_ny,
                )
            )

    print("TODAY'S RECENT OBSERVATIONS")
    print("---------------------------")

    if not today_rows:
        print(
            "No observations retrieved today."
        )
        print()
        print(
            "RESULT: COLLECTOR NOT CONFIRMED"
        )
        return 1

    for (
        row,
        retrieved,
        retrieved_ny,
    ) in today_rows[:20]:
        (
            observation_id,
            ticker,
            provider,
            bar_start_text,
            _,
            opened,
            high,
            low,
            closed,
            volume,
        ) = row

        bar_start = parse_datetime(
            bar_start_text
        )

        print(
            f"{ticker:<7} "
            f"bar="
            f"{bar_start.astimezone(NEW_YORK):%H:%M:%S} "
            f"retrieved={retrieved_ny:%H:%M:%S} "
            f"close={closed} "
            f"provider={provider}"
        )

    latest_row, latest_retrieved, latest_ny = (
        today_rows[0]
    )

    age_seconds = (
        now_utc - latest_retrieved
    ).total_seconds()

    tickers_today = sorted(
        {
            row[0][1]
            for row in today_rows
        }
    )

    print()
    print("SUMMARY")
    print("-------")
    print(
        "Today observations in latest sample: "
        f"{len(today_rows)}"
    )
    print(
        "Tickers observed today: "
        + ", ".join(tickers_today)
    )
    print(
        f"Latest retrieval: "
        f"{latest_ny.isoformat()}"
    )
    print(
        f"Latest observation age: "
        f"{age_seconds:.0f} seconds"
    )
    print()

    if age_seconds <= 300:
        print(
            "RESULT: RECENT COLLECTION CONFIRMED"
        )
        return 0

    print(
        "RESULT: DATA EXISTS TODAY, "
        "BUT COLLECTION IS NOT CURRENT"
    )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())