"""GEO-ASSET ZA public API (FastAPI). Read-only; connects as the public application role (web_app).

    uvicorn api.main:app --host 0.0.0.0 --port 8000

The role can read the api schema and nothing else, its sessions are read-only with a 5 second statement timeout,
and every query is parameterised. Write operations are deliberately absent from the public API.
"""
import datetime as dt
import decimal
import os
import pathlib
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import queries as q  # noqa: E402
from gaz.db import dsn  # noqa: E402

pool: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(app):
    global pool
    user = os.environ.get("GAZ_WEB_USER", "web_app")
    pw = os.environ.get("GAZ_PASSWORD_WEB_APP") or os.environ.get("GAZ_DEMO_PASSWORD")
    pool = ConnectionPool(dsn(user=user, password=pw), min_size=1, max_size=int(os.environ.get("GAZ_API_POOL", "5")),
                          kwargs={"application_name": "geo-asset-za-api", "autocommit": True}, open=True)
    yield
    pool.close()


app = FastAPI(title="GEO-ASSET ZA API", version="1.0", lifespan=lifespan,
              description="Read-only access to the GEO-ASSET ZA demonstration register. Asset attributes and maintenance records are synthetic.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def _json(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _json(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json(x) for x in v]
    return v


def run(fn, *args, **kw):
    with pool.connection() as conn:
        return JSONResponse(_json(fn(conn, *args, **kw)))


@app.get("/api/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/kpis")
def kpis():
    return run(q.kpis)


@app.get("/api/summary")
def summary():
    return run(q.summary_by_type)


@app.get("/api/spend")
def spend():
    return run(q.spend_by_month)


@app.get("/api/priorities")
def priorities(limit: int = Query(25, ge=1, le=200)):
    return run(q.priorities, limit)


@app.get("/api/performance")
def performance():
    return run(q.work_order_performance)


@app.get("/api/lookups")
def lookups():
    return run(q.lookups)


@app.get("/api/wards")
def wards():
    return run(q.wards)


@app.get("/api/assets")
def assets(asset_class: str | None = Query(None, alias="class", pattern="^[A-Z]{2,6}$"),
           type: str | None = Query(None, pattern="^[A-Z_]{3,30}$"),
           ward: int | None = Query(None, ge=1, le=200),
           condition: int | None = Query(None, ge=1, le=5),
           bbox: str | None = Query(None, pattern=r"^-?\d+(\.\d+)?(,-?\d+(\.\d+)?){3}$", description="minLon,minLat,maxLon,maxLat"),
           limit: int = Query(5000, ge=1, le=20000)):
    return run(q.assets_geojson, asset_class, type, ward, condition, bbox.split(",") if bbox else None, limit)


@app.get("/api/assets/{code}")
def asset(code: str):
    if not (3 <= len(code) <= 20):
        raise HTTPException(404, "Unknown asset code")
    with pool.connection() as conn:
        a = q.asset(conn, code.upper())
    if not a:
        raise HTTPException(404, "Unknown asset code")
    return JSONResponse(_json(a))


# The demonstration front-end, served from the same origin when present
if (ROOT / "web").exists():
    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
