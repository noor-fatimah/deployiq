# database.py — DeployIQ
# PostgreSQL backend using asyncpg with connection pooling.
# Supports thousands of concurrent clients.
#
# FREE PostgreSQL options (just set DATABASE_URL):
#   • Neon        → https://neon.tech           (free 0.5 GB, serverless, recommended)
#   • Supabase    → https://supabase.com         (free 500 MB)
#   • Railway     → https://railway.app          (free $5 credit)
#   • ElephantSQL → https://www.elephantsql.com  (free 20 MB)
#
# DATABASE_URL format:
#   postgresql://user:password@host:5432/dbname
#   For Neon, add ?sslmode=require at the end.

import os
import asyncpg
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Global connection pool ─────────────────────────────────────────────────────
_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Get a free PostgreSQL URL from neon.tech or supabase.com."
            )
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=5,          # always-ready connections
            max_size=50,         # scales to 50 concurrent queries (handles 1000s of reqs)
            command_timeout=30,
            max_inactive_connection_lifetime=300,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Schema ─────────────────────────────────────────────────────────────────────
async def init_db():
    """Create tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id                  TEXT PRIMARY KEY,
                filename            TEXT,
                file_size_bytes     INTEGER,
                file_type           TEXT,
                client_ip           TEXT,
                status              TEXT DEFAULT 'processing',
                task_type           TEXT,
                risk_level          TEXT,
                processing_time     REAL,
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_created_at
            ON requests(created_at DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_status
            ON requests(status)
        """)


# ── Write helpers ──────────────────────────────────────────────────────────────
async def log_request(
    unique_id: str,
    filename: str,
    file_size: int,
    client_ip: str,
    file_type: str = "csv",
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO requests (id, filename, file_size_bytes, file_type, client_ip)
               VALUES ($1, $2, $3, $4, $5)""",
            unique_id, filename, file_size, file_type, client_ip,
        )


async def update_request_status(
    unique_id: str,
    status: str,
    task_type=None,
    risk_level=None,
    processing_time=None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE requests
               SET status=$1, task_type=$2, risk_level=$3,
                   processing_time=$4, updated_at=NOW()
               WHERE id=$5""",
            status, task_type, risk_level, processing_time, unique_id,
        )


# ── Read helpers ───────────────────────────────────────────────────────────────
async def get_stats():
    """Return usage stats for the /stats endpoint."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        total    = await conn.fetchval("SELECT COUNT(*) FROM requests")
        success  = await conn.fetchval(
            "SELECT COUNT(*) FROM requests WHERE status='success'")
        errors   = await conn.fetchval(
            "SELECT COUNT(*) FROM requests WHERE status LIKE 'error%'")
        today    = await conn.fetchval(
            "SELECT COUNT(*) FROM requests WHERE created_at::date = CURRENT_DATE")
        avg_time = await conn.fetchval(
            "SELECT AVG(processing_time) FROM requests WHERE status='success'")
        risk_rows = await conn.fetch(
            """SELECT risk_level, COUNT(*) AS count
               FROM requests WHERE risk_level IS NOT NULL
               GROUP BY risk_level""")
        task_rows = await conn.fetch(
            """SELECT task_type, COUNT(*) AS count
               FROM requests WHERE task_type IS NOT NULL
               GROUP BY task_type""")
        type_rows = await conn.fetch(
            """SELECT file_type, COUNT(*) AS count
               FROM requests WHERE file_type IS NOT NULL
               GROUP BY file_type""")

    return {
        "total_reports":          total,
        "successful_reports":     success,
        "failed_reports":         errors,
        "reports_today":          today,
        "avg_processing_time_sec": round(avg_time, 2) if avg_time else None,
        "risk_distribution":      {r["risk_level"]: r["count"] for r in risk_rows},
        "task_distribution":      {r["task_type"]:  r["count"] for r in task_rows},
        "file_type_distribution": {r["file_type"]:  r["count"] for r in type_rows},
    }
