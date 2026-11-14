"""Create the demonstration login roles and put each in its group role.

    python administration/security/create_login_roles.py

Passwords come from the environment, never from the repository: GAZ_PASSWORD_<LOGIN> (for example
GAZ_PASSWORD_WEB_APP) if set, otherwise GAZ_DEMO_PASSWORD. If neither is set the role is created without a
password, which only works where pg_hba.conf trusts local connections (CI and development containers).
Safe to run again: existing roles are updated, not recreated.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from psycopg import sql  # noqa: E402
from gaz.db import connect, login_password  # noqa: E402

LOGINS = [
    # login,          group,           connection limit
    ("dba_admin",     "gaz_admin",     5),
    ("manager_demo",  "gaz_manager",   10),
    ("inspector_a",   "gaz_inspector", 5),
    ("inspector_b",   "gaz_inspector", 5),
    ("inspector_c",   "gaz_inspector", 5),
    ("analyst_demo",  "gaz_analyst",   5),
    ("etl_runner",    "gaz_etl",       3),
    ("web_app",       "gaz_web",       20),
    ("monitor",       "gaz_monitor",   3),
]

# Role settings (ALTER ROLE ... SET) are not inherited through group membership, so the session limits for the
# public application and the analyst are applied to the login roles themselves.
SETTINGS = {
    "gaz_web":     {"default_transaction_read_only": "on", "statement_timeout": "5s", "idle_in_transaction_session_timeout": "10s"},
    "gaz_analyst": {"statement_timeout": "2min"},
}


def main():
    with connect(app="create_login_roles") as conn:
        for login, group, limit in LOGINS:
            pw = login_password(login)
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
            verb = sql.SQL("ALTER") if exists else sql.SQL("CREATE")
            stmt = sql.SQL("{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT {}").format(
                verb, sql.Identifier(login), sql.Literal(limit))
            if pw:
                stmt = stmt + sql.SQL(" PASSWORD {}").format(sql.Literal(pw))
            conn.execute(stmt)
            conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login)))
            for name, value in SETTINGS.get(group, {}).items():
                conn.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(sql.Identifier(login), sql.Identifier(name), sql.Literal(value)))
            print(f"{'updated' if exists else 'created'} {login:14s} in {group}{'' if pw else '  (no password)'}")
        conn.commit()


if __name__ == "__main__":
    main()
