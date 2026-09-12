from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


@event.listens_for(
    Engine,
    "connect",
)
def _enable_sqlite_foreign_keys(
    dbapi_connection,
    connection_record,
):
    """
    Enable SQLite foreign-key enforcement
    for every SQLite connection.
    """

    if isinstance(
        dbapi_connection,
        sqlite3.Connection,
    ):
        cursor = dbapi_connection.cursor()

        cursor.execute(
            "PRAGMA foreign_keys=ON"
        )

        cursor.close()


def create_sqlite_engine(
    database_path: str | Path,
):
    """
    Create the project's standard SQLite engine.
    """

    path = Path(
        database_path
    ).expanduser()

    return create_engine(
        f"sqlite:///{path}",
        future=True,
    )