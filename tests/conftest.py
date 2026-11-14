"""Shared fixtures. Every test runs inside a transaction that is rolled back, so the suite leaves no trace.

Connection settings come from PG* environment variables; login-role passwords from GAZ_DEMO_PASSWORD (or none,
where local connections are trusted, as in CI).
"""
import os
import pathlib
import sys

import psycopg
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gaz.db import connect  # noqa: E402

HATFIELD = "ST_SetSRID(ST_MakePoint(28.2370, -25.7480), 4326)"     # inside ward 56
JOHANNESBURG = "ST_SetSRID(ST_MakePoint(28.0473, -26.2041), 4326)"  # outside the study area


@pytest.fixture
def db():
    """Superuser connection in a transaction that is rolled back."""
    conn = connect(app="pytest")
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def as_role():
    """Factory: as_role('web_app') returns a connection as that login role, rolled back at the end."""
    opened = []

    def _open(login):
        pw = os.environ.get(f"GAZ_PASSWORD_{login.upper()}") or os.environ.get("GAZ_DEMO_PASSWORD")
        conn = connect(user=login, password=pw, app="pytest")
        opened.append(conn)
        return conn

    yield _open
    for c in opened:
        c.rollback()
        c.close()


def raises(conn, exc, statement, params=None):
    """Run a statement inside a savepoint and assert it fails with the given psycopg error class."""
    with pytest.raises(exc):
        with conn.transaction():
            conn.execute(statement, params)


@pytest.fixture
def sample(db):
    """Codes of existing records to test against."""
    return {
        "streetlight": db.execute("SELECT asset_id, asset_code FROM assets.infrastructure_assets WHERE type_code = 'STREETLIGHT' ORDER BY asset_id LIMIT 1").fetchone(),
        "road": db.execute("SELECT asset_id, asset_code FROM assets.infrastructure_assets WHERE type_code = 'ROAD_SEGMENT' ORDER BY asset_id LIMIT 1").fetchone(),
        "inspection_b": db.execute("SELECT inspection_id FROM maintenance.inspections WHERE inspector = 'inspector_b' ORDER BY inspection_id LIMIT 1").fetchone()[0],
        "work_order": db.execute("SELECT work_order_id FROM maintenance.work_orders WHERE status = 'COMPLETED' ORDER BY work_order_id LIMIT 1").fetchone()[0],
    }


errors = psycopg.errors
