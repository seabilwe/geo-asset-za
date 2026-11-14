# Security and access control

## Principles

- **Least privilege.** Every role can do its job and nothing else. Nothing is granted to `PUBLIC`.
- **Group roles carry privileges; people log in as members.** Changing what inspectors may do is one `GRANT`, and
  removing a person is one `DROP ROLE`.
- **No superuser at run time.** All objects belong to `gaz_owner`, an ordinary role nobody logs in as. Migrations
  and backups run as the superuser; the API, imports, analysts and inspectors never do.
- **The public sees views, never tables.** The web application role reads only the `api` schema, in read-only
  sessions with a 5 second statement timeout.
- **No passwords in the repository.** Login roles get passwords from environment variables (`.env`, ignored by git).

## Roles

| Group role | Purpose | Can | Cannot |
|---|---|---|---|
| `gaz_owner` | Owns every object | Everything on its objects | Log in |
| `gaz_admin` | Database administrator | Act as owner; read all statistics (`pg_monitor`) | Act as superuser |
| `gaz_manager` | Infrastructure manager | Read everything; add and edit assets and maintenance; refresh reports; read the audit log | Delete an asset; change reference data; change the audit log |
| `gaz_inspector` | Field inspector | Read the register; record inspections in their own name; edit only their own inspections; change an asset's status | Edit other columns; delete anything; raise work orders; read the audit log |
| `gaz_analyst` | Data analyst | Read reporting and API views | Read base tables; write anything |
| `gaz_etl` | Import process | Load staging tables; run validation and promotion | Read or write the register directly |
| `gaz_web` | Public web application | Read the `api` views | Anything else; sessions are read-only |
| `gaz_monitor` | Monitoring | Read admin views and PostgreSQL statistics | Read any asset data |

Demonstration logins: `dba_admin`, `manager_demo`, `inspector_a`, `inspector_b`, `inspector_c` (one per ward),
`analyst_demo`, `etl_runner`, `web_app`, `monitor`.

The full table-by-table matrix is generated from the catalog: [privilege_matrix.md](privilege_matrix.md).

## Techniques used

| Technique | Where |
|---|---|
| Schema-level `USAGE` grants | V011 |
| Column-level privilege (inspector may update `status_code` and `decommission_date` only) | V011 |
| Row-level security (inspectors insert and edit only their own inspections) | V012 |
| `SECURITY DEFINER` functions with a fixed `search_path`, owned by a non-superuser | `staging.validate_batch`, `staging.promote_batch`, `audit.log_change`, `operations.refresh_reporting` |
| Revoking PostgreSQL's default `EXECUTE` on functions from `PUBLIC` | V011, V014 |
| `security_barrier` views for the public API | V008 |
| Per-role session settings: read-only, statement and idle timeouts | `create_login_roles.py` |
| Connection limits per login | `create_login_roles.py` |
| Database `CONNECT` revoked from `PUBLIC` | V011 |
| Append-only audit trail written through a definer function | V005 |
| Database port bound to 127.0.0.1 only in Docker | `docker-compose.yml` |

## What the tests found

`tests/test_security.py` checks every row of the table above by connecting as each login and trying both what it
should and should not be able to do. Writing those tests found two real gaps:

1. **A function left executable by everyone.** `admin.apply_ownership()` was created after the migration that
   revoked `EXECUTE` from `PUBLIC`, so PostgreSQL's default grant applied to it. Fixed in migration V014, and the
   test `test_no_privileges_left_to_public` now checks every function and table in the application schemas.
2. **Session settings are not inherited.** `ALTER ROLE gaz_web SET default_transaction_read_only = on` has no effect
   on `web_app`, a member of `gaz_web`: PostgreSQL applies role settings only for the role that logs in. The settings
   are now applied to the login roles by `create_login_roles.py`, and `test_web_session_is_read_only` checks them.

## Public deployment

The public portfolio page does not connect to the database at all: it reads a static snapshot exported through
the same `api` views. If the API were deployed publicly it would run as `web_app`, behind HTTPS, with only `GET`
endpoints, parameterised queries and input validation (tested in `tests/test_api.py`), and with the database
reachable only from the API host.
