# saas_scheduler.py — DeployIQ SaaS
# Background job to send trial expiry emails
# Run this as a separate process OR integrate into the main app

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

FRONTEND_URL             = os.getenv("FRONTEND_URL", "http://localhost:8001")
LEMON_SQUEEZY_STORE_URL  = os.getenv("LEMON_SQUEEZY_STORE_URL", "")


async def run_expiry_checks():
    """
    Check for:
    1. Users whose trial expires in 1 day → send reminder
    2. Users whose trial expired → send expiry email (once)
    """
    from saas_database import get_pool, mark_expiry_email_sent
    from saas_email import send_trial_expired_email, send_trial_reminder_email

    pool = await get_pool()
    now  = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        # ── Trial expired — send expiry email once ────────────────────────────
        expired_users = await conn.fetch("""
            SELECT id, email FROM saas_users
            WHERE plan = 'trial'
              AND trial_end_date < NOW()
              AND expiry_email_sent = FALSE
        """)

        for user in expired_users:
            checkout_url = (
                LEMON_SQUEEZY_STORE_URL
                + f"?checkout[email]={user['email']}"
            )
            send_trial_expired_email(user["email"], checkout_url)
            await mark_expiry_email_sent(user["id"])
            logger.info(f"Sent expiry email → {user['email']}")

        # ── Expiring in 1 day — send reminder ────────────────────────────────
        reminder_users = await conn.fetch("""
            SELECT id, email, access_token FROM saas_users
            WHERE plan = 'trial'
              AND trial_end_date BETWEEN NOW() AND NOW() + INTERVAL '25 hours'
              AND expiry_email_sent = FALSE
        """)

        for user in reminder_users:
            # Reconstruct access URL (token is stored directly)
            deployiq_url  = os.getenv("DEPLOYIQ_AGENT_URL", "")
            access_url    = f"{deployiq_url}?token={user['access_token']}"
            checkout_url  = LEMON_SQUEEZY_STORE_URL + f"?checkout[email]={user['email']}"
            send_trial_reminder_email(user["email"], access_url, checkout_url, days_left=1)
            logger.info(f"Sent 1-day reminder → {user['email']}")


async def scheduler_loop():
    """Run checks every hour."""
    while True:
        try:
            await run_expiry_checks()
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
        await asyncio.sleep(3600)  # 1 hour


if __name__ == "__main__":
    asyncio.run(scheduler_loop())
