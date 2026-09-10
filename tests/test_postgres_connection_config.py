from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import src.infrastructure.postgres.connection as connection


def _valid_environment() -> dict[str, str]:
    return {
        "POSTGRES_HOST": "db.internal",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "governance",
        "POSTGRES_USER": "pipeline",
        "POSTGRES_PASSWORD": "test-password",
    }


def test_importing_connection_module_does_not_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_connect(**_kwargs: object) -> None:
        raise AssertionError("connection opened during import")

    monkeypatch.setattr(connection.psycopg, "connect", unexpected_connect)

    importlib.reload(connection)


def test_loads_valid_postgres_config_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect_calls: list[object] = []
    monkeypatch.setattr(
        connection.psycopg,
        "connect",
        lambda **kwargs: connect_calls.append(kwargs),
    )

    config = connection.load_postgres_config(_valid_environment())

    assert config.safe_target() == {
        "host": "db.internal",
        "port": 5432,
        "database": "governance",
        "user": "pipeline",
    }
    assert connect_calls == []


def test_operational_loader_uses_dotenv_not_env_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    monkeypatch.setattr(connection, "load_dotenv", loaded_paths.append)
    for name, value in _valid_environment().items():
        monkeypatch.setenv(name, value)

    connection.load_postgres_config()

    assert loaded_paths == [connection.PROJECT_ROOT / ".env"]
    assert all(path.name != ".env.example" for path in loaded_paths)


@pytest.mark.parametrize(
    "missing_name",
    [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ],
)
def test_missing_required_field_fails_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    environment = _valid_environment()
    environment.pop(missing_name)
    connect_calls: list[object] = []
    monkeypatch.setattr(
        connection.psycopg,
        "connect",
        lambda **kwargs: connect_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match=missing_name):
        connection.load_postgres_config(environment)

    assert connect_calls == []


@pytest.mark.parametrize("port", ["invalid", "0", "65536"])
def test_invalid_port_fails_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    port: str,
) -> None:
    environment = _valid_environment()
    environment["POSTGRES_PORT"] = port
    connect_calls: list[object] = []
    monkeypatch.setattr(
        connection.psycopg,
        "connect",
        lambda **kwargs: connect_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="POSTGRES_PORT"):
        connection.load_postgres_config(environment)

    assert connect_calls == []


def test_password_is_excluded_from_repr_and_errors() -> None:
    environment = _valid_environment()
    password = environment["POSTGRES_PASSWORD"]
    config = connection.load_postgres_config(environment)

    assert password not in repr(config)
    assert "password" not in config.safe_target()

    environment["POSTGRES_PORT"] = "not-a-port"
    with pytest.raises(RuntimeError) as exc_info:
        connection.load_postgres_config(environment)
    assert password not in str(exc_info.value)


def test_connection_is_opened_only_after_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    captured: dict[str, object] = {}
    config = connection.load_postgres_config(_valid_environment())
    monkeypatch.setattr(connection, "load_postgres_config", lambda: config)

    def connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(connection.psycopg, "connect", connect)

    result = connection.get_postgres_connection()

    assert result is sentinel
    assert captured == {
        "host": "db.internal",
        "port": 5432,
        "dbname": "governance",
        "user": "pipeline",
        "password": config.password,
    }
