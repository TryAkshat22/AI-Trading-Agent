
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from database.storage import get_default_database_path


MODEL_2_VERSION = "model-2-flexible"
MODEL_2_ACCOUNT_ID = "model2-paper"


class Model2ConfigurationError(Exception):
    """Model 2 configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class Model2Paths:
    model1_database: Path
    model2_database: Path
    observation_database: Path


def get_model2_paths() -> Model2Paths:
    """
    Resolve paths without creating or modifying any files.

    Model 1 trading data and intraday observations currently
    live in the original database.

    Model 2 will read observations from that database but
    write its own trading records to a different database.
    """

    model1_database = (
        get_default_database_path()
        .expanduser()
        .resolve()
    )

    configured_model2 = os.getenv(
        "PAPER_TRADING_MODEL2_DB_PATH"
    )

    if configured_model2:
        model2_database = (
            Path(configured_model2)
            .expanduser()
            .resolve()
        )
    else:
        model2_database = (
            model1_database.parent
            / "trading_agent_model2.db"
        ).resolve()

    if model1_database == model2_database:
        raise Model2ConfigurationError(
            "Model 2 database must be different "
            "from the Model 1 database."
        )

    if model2_database.exists() and not model2_database.is_file():
        raise Model2ConfigurationError(
            "Model 2 database path is not a file."
        )

    return Model2Paths(
        model1_database=model1_database,
        model2_database=model2_database,
        observation_database=model1_database,
    )