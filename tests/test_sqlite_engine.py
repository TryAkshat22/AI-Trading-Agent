from sqlalchemy import text

from database.sqlite_engine import (
    create_sqlite_engine,
)


def test_sqlite_foreign_keys_are_enabled(
    tmp_path,
):

    engine = create_sqlite_engine(
        tmp_path / "test.db"
    )

    with engine.connect() as connection:

        result = connection.execute(
            text(
                "PRAGMA foreign_keys"
            )
        ).scalar_one()

    assert result == 1