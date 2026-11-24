
from pathlib import Path

import pytest

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    Model2ConfigurationError,
    get_model2_paths,
)


def test_model2_uses_separate_database(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "trading_agent.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.delenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        raising=False,
    )

    paths = get_model2_paths()

    assert paths.model1_database == model1.resolve()
    assert paths.model2_database != paths.model1_database
    assert paths.model2_database.name == (
        "trading_agent_model2.db"
    )


def test_observations_remain_in_original_database(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "trading_agent.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.delenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        raising=False,
    )

    paths = get_model2_paths()

    assert (
        paths.observation_database
        == paths.model1_database
    )


def test_same_database_is_rejected(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "trading_agent.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model1),
    )

    with pytest.raises(Model2ConfigurationError):
        get_model2_paths()


def test_configuration_does_not_create_database(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "trading_agent.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.delenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        raising=False,
    )

    paths = get_model2_paths()

    assert not paths.model1_database.exists()
    assert not paths.model2_database.exists()


def test_model_identity_is_explicit():
    assert MODEL_2_VERSION == "model-2-flexible"
    assert MODEL_2_ACCOUNT_ID == "model2-paper"