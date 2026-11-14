"""Run the routine database jobs on a schedule (the scheduler service in docker-compose.yml).

    python administration/scheduler.py            run forever
    python administration/scheduler.py --once     run every job once now, then exit

  every hour         health report            administration/monitoring/health_report.py
  daily   01:30      refresh reporting views  operations.refresh_reporting()
  daily   02:00      backup                   administration/backup/backup.py (keeps 7)
  Sunday  03:00      restore test             administration/restore/restore_test.py

Times are in the container's time zone (TZ, Africa/Johannesburg in docker-compose.yml). In production the same jobs
could run from pg_cron inside PostgreSQL or from the operating system's scheduler; a small Python loop keeps the
demonstration self-contained. Each run is logged in admin.job_runs.
"""
import argparse
import datetime as dt
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaz.db import connect  # noqa: E402

JOBS = [
    # name,              due(now) -> bool,                                                       command
    ("health_report",    lambda t: t.minute == 0,                                                 ["administration/monitoring/health_report.py", "--json", "administration/monitoring/latest_health.json"]),
    ("refresh_reporting", lambda t: (t.hour, t.minute) == (1, 30),                                None),
    ("backup",           lambda t: (t.hour, t.minute) == (2, 0),                                  ["administration/backup/backup.py", "--keep", "7"]),
    ("restore_test",     lambda t: t.weekday() == 6 and (t.hour, t.minute) == (3, 0),             ["administration/restore/restore_test.py"]),
]


def run(name, cmd):
    with connect(autocommit=True, app="scheduler") as conn:
        run_id = conn.execute("INSERT INTO admin.job_runs (job_name) VALUES (%s) RETURNING run_id", (name,)).fetchone()[0]
        if cmd is None:
            conn.execute("SELECT operations.refresh_reporting()")
            status, msg = "SUCCESS", "refreshed"
        else:
            p = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
            # health_report exits 2 on warnings: the job itself succeeded
            status = "SUCCESS" if p.returncode in (0, 2) else "FAILED"
            msg = (p.stdout + p.stderr).strip()[-1500:]
        conn.execute("UPDATE admin.job_runs SET finished_at = clock_timestamp(), status = %s, message = %s WHERE run_id = %s", (status, msg, run_id))
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} {name}: {status}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.once:
        for name, _, cmd in JOBS:
            run(name, cmd)
        return
    print("scheduler started", flush=True)
    last = None
    while True:
        now = dt.datetime.now().replace(second=0, microsecond=0)
        if now != last:
            last = now
            for name, due, cmd in JOBS:
                if due(now):
                    try:
                        run(name, cmd)
                    except Exception as e:          # keep the scheduler alive; the failure is visible in the log
                        print(f"{now:%Y-%m-%d %H:%M} {name}: ERROR {e}", flush=True)
        time.sleep(20)


if __name__ == "__main__":
    main()
