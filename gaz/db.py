"""Database connections for GEO-ASSET ZA scripts.

Connection settings come from the standard libpq environment variables (PGHOST, PGPORT, PGDATABASE, PGUSER,
PGPASSWORD), which docker-compose.yml and the CI workflow set. Nothing is hard-coded.
"""
import os
import psycopg

DEFAULT_DB = "geoasset_za"


def login_password(login: str) -> str | None:
    """Password for a demonstration login role: GAZ_PASSWORD_<LOGIN> if set, else GAZ_DEMO_PASSWORD, else None (trust auth)."""
    return os.environ.get(f"GAZ_PASSWORD_{login.upper()}") or os.environ.get("GAZ_DEMO_PASSWORD")


def dsn(user: str | None = None, dbname: str | None = None, password: str | None = None) -> str:
    parts = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "dbname": dbname or os.environ.get("PGDATABASE", DEFAULT_DB),
        "user": user or os.environ.get("PGUSER", "postgres"),
    }
    pw = password if password is not None else (os.environ.get("PGPASSWORD") if user is None else None)
    if pw:
        parts["password"] = pw
    return " ".join(f"{k}={v}" for k, v in parts.items())


def connect(user: str | None = None, dbname: str | None = None, password: str | None = None, autocommit: bool = False, app: str = "geo-asset-za"):
    return psycopg.connect(dsn(user, dbname, password), autocommit=autocommit, application_name=app)
