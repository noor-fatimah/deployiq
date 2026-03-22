# saas_database.py — DeployIQ SaaS
# PostgreSQL (Neon) using asyncpg with connection pooling

import os
import asyncpg
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Get a free PostgreSQL URL from neon.tech"
            )
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=20,
            command_timeout=30,
            max_inactive_connection_lifetime=300,
        )
    return _pool


async def close_saas_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Schema ─────────────────────────────────────────────────────────────────────
async def init_saas_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS saas_users (
                id                  TEXT PRIMARY KEY,
                email               TEXT UNIQUE NOT NULL,
                plan                TEXT DEFAULT 'trial',
                access_token        TEXT,
                trial_start_date    TIMESTAMPTZ DEFAULT NOW(),
                trial_end_date      TIMESTAMPTZ,
                reports_used        INTEGER DEFAULT 0,
                max_reports_trial   INTEGER DEFAULT 2,
                expiry_email_sent   BOOLEAN DEFAULT FALSE,
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_saas_users_email
            ON saas_users(email)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_saas_users_token
            ON saas_users(access_token)
        """)

        # Usage logs table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS saas_usage_logs (
                id                  SERIAL PRIMARY KEY,
                user_id             TEXT REFERENCES saas_users(id) ON DELETE CASCADE,
                report_generated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_saas_usage_user_id
            ON saas_usage_logs(user_id)
        """)


# ── Write helpers ──────────────────────────────────────────────────────────────
async def create_user(
    user_id: str,
    email: str,
    plan: str,
    token: str,
    trial_start,
    trial_end,
    max_reports: int = 2,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO saas_users
               (id, email, plan, access_token, trial_start_date, trial_end_date, max_reports_trial)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (email) DO NOTHING""",
            user_id, email, plan, token, trial_start, trial_end, max_reports,
        )


async def increment_reports_used(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE saas_users
               SET reports_used = reports_used + 1, updated_at = NOW()
               WHERE id = $1""",
            user_id,
        )


async def upgrade_user_to_paid(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE saas_users
               SET plan = 'paid', max_reports_trial = 999999, updated_at = NOW()
               WHERE id = $1""",
            user_id,
        )


async def log_usage(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO saas_usage_logs (user_id) VALUES ($1)",
            user_id,
        )


async def mark_expiry_email_sent(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE saas_users SET expiry_email_sent = TRUE WHERE id = $1",
            user_id,
        )


# ── Read helpers ───────────────────────────────────────────────────────────────
async def get_user_by_email(email: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM saas_users WHERE email = $1", email
        )


async def get_user_by_token(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM saas_users WHERE id = $1", user_id
        )


async def get_user_status_data(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM saas_users WHERE id = $1", user_id
        )


# ── Admin helpers ──────────────────────────────────────────────────────────────
async def get_all_users(limit: int = 100, offset: int = 0):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, email, plan, reports_used, max_reports_trial,
                      trial_start_date, trial_end_date, created_at
               FROM saas_users
               ORDER BY created_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset,
        )


async def get_saas_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        total     = await conn.fetchval("SELECT COUNT(*) FROM saas_users")
        trial     = await conn.fetchval("SELECT COUNT(*) FROM saas_users WHERE plan='trial'")
        paid      = await conn.fetchval("SELECT COUNT(*) FROM saas_users WHERE plan='paid'")
        today     = await conn.fetchval(
            "SELECT COUNT(*) FROM saas_users WHERE created_at::date = CURRENT_DATE"
        )
        reports   = await conn.fetchval("SELECT SUM(reports_used) FROM saas_users")
        return {
            "total_users":   total,
            "trial_users":   trial,
            "paid_users":    paid,
            "signups_today": today,
            "total_reports": reports or 0,
            "conversion_rate": f"{(paid / total * 100):.1f}%" if total else "0%",
        }
