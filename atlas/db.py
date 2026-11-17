import hashlib
import os
import secrets
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def database_url():
    return os.environ.get("DATABASE_URL", "postgresql://atlas:atlas@localhost:5432/atlas")


def pool():
    return ConnectionPool(
        database_url(),
        min_size=1,
        max_size=8,
        timeout=5,
        kwargs={"row_factory": dict_row, "options": "-c statement_timeout=5000"},
    )


def migrate():
    with psycopg.connect(database_url()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(702341)")
        conn.execute(Path(__file__).with_name("schema.sql").read_text())


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def provision(name):
    tenant = uuid4()
    tokens = {role: secrets.token_urlsafe(32) for role in ("reader", "investigator", "ingestor")}
    with psycopg.connect(database_url()) as conn:
        conn.execute("INSERT INTO tenants(id,name) VALUES (%s,%s)", (tenant, name))
        for role, token in tokens.items():
            conn.execute(
                "INSERT INTO credentials VALUES (%s,%s,%s,false)", (token_digest(token), tenant, role)
            )
    return {"tenant_id": str(tenant), **tokens}
