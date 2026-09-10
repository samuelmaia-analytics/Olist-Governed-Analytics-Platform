import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)

    def safe_target(self) -> dict[str, str | int]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
        }


def load_postgres_config(
    environ: Mapping[str, str] | None = None,
) -> PostgresConfig:
    if environ is None:
        load_dotenv(PROJECT_ROOT / ".env")
        environ = os.environ

    variable_names = {
        "host": "POSTGRES_HOST",
        "port": "POSTGRES_PORT",
        "database": "POSTGRES_DB",
        "user": "POSTGRES_USER",
        "password": "POSTGRES_PASSWORD",
    }
    missing = [
        variable_name
        for variable_name in variable_names.values()
        if not environ.get(variable_name, "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required PostgreSQL configuration: " + ", ".join(missing)
        )

    raw_port = environ[variable_names["port"]]
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(
            "POSTGRES_PORT must be an integer between 1 and 65535."
        ) from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(
            "POSTGRES_PORT must be an integer between 1 and 65535."
        )

    return PostgresConfig(
        host=environ[variable_names["host"]].strip(),
        port=port,
        database=environ[variable_names["database"]].strip(),
        user=environ[variable_names["user"]].strip(),
        password=environ[variable_names["password"]],
    )


def get_postgres_connection():
    config = load_postgres_config()
    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
    )
