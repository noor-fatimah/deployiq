# saas_main.py — DeployIQ SaaS Layer
# Handles: Auth, Trial, Payments, Email, User Management
# Stack: FastAPI + Neon PostgreSQL + Lemon Squeezy + SMTP

from dotenv import load_dotenv
load_dotenv()

import os
import uuid
import hmac
import hashlib
import logging
import logging.handlers
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from saas_database import (
    init_saas_db, create_user, get_user_by_email, get_user_by_token,
    increment_reports_used, upgrade_user_to_paid, log_usage,
    get_user_status_data, close_saas_pool
)
from saas_email import (
    send_trial_started_email, send_trial_expired_email,
    send_payment_success_email, send_trial_reminder_email
)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            "saas.log", maxBytes=5 * 1024 * 1024, backupCount=3
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DEPLOYIQ_AGENT_URL      = os.getenv("DEPLOYIQ_AGENT_URL", "https://your-app.railway.app")
LEMON_SQUEEZY_SECRET    = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "")
LEMON_SQUEEZY_STORE_URL = os.getenv("LEMON_SQUEEZY_STORE_URL", "https://yourstore.lemonsqueezy.com/checkout/buy/your-product-id")
JWT_SECRET              = os.getenv("JWT_SECRET", "change-me-in-production-use-long-random-string")
TRIAL_DAYS              = int(os.getenv("TRIAL_DAYS", 7))
TRIAL_MAX_REPORTS       = int(os.getenv("TRIAL_MAX_REPORTS", 2))
PAID_DAILY_LIMIT        = int(os.getenv("PAID_DAILY_LIMIT", 100))   # 0 = unlimited
FRONTEND_URL            = os.getenv("FRONTEND_URL", "http://localhost:8001")


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_saas_db()
    logger.info("DeployIQ SaaS started ✓")
    yield
    await close_saas_pool()
    logger.info("DeployIQ SaaS shutdown")


# ── App ────────────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="DeployIQ SaaS",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("ENV") == "production" else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory="templates")

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass


# ── Token helpers ──────────────────────────────────────────────────────────────
def generate_access_token(email: str, user_id: str) -> str:
    """Generate a signed access token (HMAC-SHA256)."""
    payload = f"{user_id}:{email}:{uuid.uuid4()}"
    sig = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    import base64
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_access_token(token: str) -> dict | None:
    """Verify and decode an access token. Returns user_id and email or None."""
    try:
        import base64
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 4:
            return None
        user_id, email, nonce, sig = parts
        payload = f"{user_id}:{email}:{nonce}"
        expected = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return {"user_id": user_id, "email": email}
    except Exception:
        return None


def _verify_lemon_squeezy_signature(payload: bytes, signature: str) -> bool:
    """Verify Lemon Squeezy webhook signature."""
    if not LEMON_SQUEEZY_SECRET:
        return True  # skip in dev
    expected = hmac.new(LEMON_SQUEEZY_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


# ── Auth dependency ────────────────────────────────────────────────────────────
async def get_current_user(request: Request) -> dict:
    token = (
        request.query_params.get("token")
        or request.headers.get("X-Access-Token")
        or request.cookies.get("deployiq_token")
    )
    if not token:
        raise HTTPException(status_code=401, detail="Access token required")

    decoded = verify_access_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await get_user_by_token(decoded["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


# ── Pydantic models ────────────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    plan: str = "trial"   # "trial" or "forever"


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Landing page ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "agent_url": DEPLOYIQ_AGENT_URL,
        "trial_days": TRIAL_DAYS,
        "trial_reports": TRIAL_MAX_REPORTS,
        "checkout_url": LEMON_SQUEEZY_STORE_URL,
    })


# ── POST /signup ───────────────────────────────────────────────────────────────
@app.post("/signup")
@limiter.limit("5/minute")
async def signup(
    request: Request,
    body: SignupRequest,
    background_tasks: BackgroundTasks,
):
    email = body.email.lower().strip()
    plan  = body.plan if body.plan in ("trial", "forever") else "trial"

    # Check if user already exists
    existing = await get_user_by_email(email)
    if existing:
        # Re-send access link
        token = generate_access_token(email, str(existing["id"]))
        access_url = f"{DEPLOYIQ_AGENT_URL}?token={token}"
        background_tasks.add_task(
            send_trial_started_email, email, access_url,
            existing["trial_end_date"], is_resend=True
        )
        return {
            "status":     "existing",
            "message":    "Access link re-sent to your email.",
            "plan":       existing["plan"],
        }

    # Create new user
    user_id = str(uuid.uuid4())
    token   = generate_access_token(email, user_id)

    trial_start = datetime.now(timezone.utc)
    trial_end   = trial_start + timedelta(days=TRIAL_DAYS)

    await create_user(
        user_id     = user_id,
        email       = email,
        plan        = plan,
        token       = token,
        trial_start = trial_start,
        trial_end   = trial_end,
        max_reports = TRIAL_MAX_REPORTS if plan == "trial" else 999999,
    )

    access_url = f"{DEPLOYIQ_AGENT_URL}?token={token}"

    if plan == "trial":
        background_tasks.add_task(
            send_trial_started_email, email, access_url, trial_end
        )
    else:
        # Forever plan — redirect to payment
        background_tasks.add_task(
            send_trial_started_email, email, access_url, trial_end, is_forever=True
        )

    logger.info(f"New signup: {email} | plan={plan}")

    return {
        "status":      "created",
        "message":     "Check your email for your access link!",
        "plan":        plan,
        "checkout_url": LEMON_SQUEEZY_STORE_URL + f"?checkout[email]={email}" if plan == "forever" else None,
    }


# ── GET /verify-token ──────────────────────────────────────────────────────────
@app.get("/verify-token")
async def verify_token(token: str, request: Request):
    decoded = verify_access_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await get_user_by_token(decoded["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check trial expiry
    now = datetime.now(timezone.utc)
    trial_end = user["trial_end_date"]
    if trial_end and trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=timezone.utc)

    if user["plan"] == "trial":
        if now > trial_end or user["reports_used"] >= user["max_reports_trial"]:
            return JSONResponse(
                status_code=402,
                content={
                    "status":       "expired",
                    "message":      "Trial expired. Upgrade to continue.",
                    "checkout_url": LEMON_SQUEEZY_STORE_URL + f"?checkout[email]={user['email']}",
                }
            )

    # Set token cookie and redirect to agent
    response = RedirectResponse(url=f"{DEPLOYIQ_AGENT_URL}?token={token}", status_code=302)
    response.set_cookie("deployiq_token", token, max_age=86400 * 30, httponly=True, samesite="lax")
    return response


# ── GET /user-status ───────────────────────────────────────────────────────────
@app.get("/user-status")
async def user_status(user: dict = Depends(get_current_user)):
    data = await get_user_status_data(user["id"])
    now  = datetime.now(timezone.utc)
    trial_end = data["trial_end_date"]
    if trial_end and trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=timezone.utc)

    days_left = max(0, (trial_end - now).days) if trial_end else 0

    return {
        "email":        data["email"],
        "plan":         data["plan"],
        "reports_used": data["reports_used"],
        "max_reports":  data["max_reports_trial"],
        "days_left":    days_left,
        "can_generate": _can_generate(data),
        "checkout_url": LEMON_SQUEEZY_STORE_URL + f"?checkout[email]={data['email']}",
    }


def _can_generate(user: dict) -> bool:
    if user["plan"] == "paid":
        return True  # unlimited (or check daily limit if desired)
    now = datetime.now(timezone.utc)
    trial_end = user["trial_end_date"]
    if trial_end and trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=timezone.utc)
    if now > trial_end:
        return False
    if user["reports_used"] >= user["max_reports_trial"]:
        return False
    return True


# ── POST /generate-report ──────────────────────────────────────────────────────
@app.post("/generate-report")
@limiter.limit("20/minute")
async def gate_generate_report(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Gate endpoint — called BEFORE the actual DeployIQ /evaluate endpoint.
    Returns 200 with proxy instructions if allowed, 402 if blocked.
    """
    if not _can_generate(user):
        now = datetime.now(timezone.utc)
        trial_end = user["trial_end_date"]
        if trial_end and trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)

        # Send expiry email once (only if trial just expired)
        if now > trial_end and user.get("expiry_email_sent") is False:
            background_tasks.add_task(
                send_trial_expired_email, user["email"],
                LEMON_SQUEEZY_STORE_URL + f"?checkout[email]={user['email']}"
            )

        return JSONResponse(
            status_code=402,
            content={
                "status":       "blocked",
                "message":      "Trial expired. Upgrade to continue.",
                "checkout_url": LEMON_SQUEEZY_STORE_URL + f"?checkout[email]={user['email']}",
            }
        )

    # Increment usage counter
    await increment_reports_used(user["id"])
    await log_usage(user["id"])

    return {
        "status":       "allowed",
        "reports_used": user["reports_used"] + 1,
        "message":      "Proceed to generate report.",
    }


# ── POST /webhook/lemon-squeezy ────────────────────────────────────────────────
@app.post("/webhook/lemon-squeezy")
async def lemon_squeezy_webhook(request: Request, background_tasks: BackgroundTasks):
    payload   = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_lemon_squeezy_signature(payload, signature):
        logger.warning("Invalid Lemon Squeezy webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    import json
    data = json.loads(payload)

    event_name = data.get("meta", {}).get("event_name", "")
    logger.info(f"Lemon Squeezy event: {event_name}")

    if event_name in ("order_created", "subscription_created"):
        attrs       = data.get("data", {}).get("attributes", {})
        email       = attrs.get("user_email", "").lower().strip()
        status      = attrs.get("status", "")
        order_total = attrs.get("total", 0)

        if not email:
            # Try nested billing_address
            email = (
                data.get("data", {})
                    .get("attributes", {})
                    .get("first_order_item", {})
                    .get("order_email", "")
            ).lower().strip()

        if email and status in ("paid", "active"):
            user = await get_user_by_email(email)
            if user:
                await upgrade_user_to_paid(str(user["id"]))
                # Generate fresh token for paid access
                token      = generate_access_token(email, str(user["id"]))
                access_url = f"{DEPLOYIQ_AGENT_URL}?token={token}"
                background_tasks.add_task(
                    send_payment_success_email, email, access_url
                )
                logger.info(f"Upgraded {email} to paid ✓")
            else:
                # New user — create paid account directly
                user_id = str(uuid.uuid4())
                token   = generate_access_token(email, user_id)
                now     = datetime.now(timezone.utc)
                await create_user(
                    user_id=user_id, email=email, plan="paid", token=token,
                    trial_start=now, trial_end=now + timedelta(days=36500),
                    max_reports=999999,
                )
                access_url = f"{DEPLOYIQ_AGENT_URL}?token={token}"
                background_tasks.add_task(
                    send_payment_success_email, email, access_url
                )
                logger.info(f"Created new paid user: {email} ✓")

    return {"received": True}


# ── GET /upgrade ───────────────────────────────────────────────────────────────
@app.get("/upgrade")
async def upgrade_redirect(email: str = ""):
    url = LEMON_SQUEEZY_STORE_URL
    if email:
        url += f"?checkout[email]={email}"
    return RedirectResponse(url=url, status_code=302)


# ── GET /success ───────────────────────────────────────────────────────────────
@app.get("/success", response_class=HTMLResponse)
async def payment_success(request: Request):
    return templates.TemplateResponse("success.html", {"request": request, "agent_url": DEPLOYIQ_AGENT_URL})


# ── GET /health ────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "DeployIQ SaaS", "timestamp": datetime.now(timezone.utc).isoformat()}
