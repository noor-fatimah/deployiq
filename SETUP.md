# DeployIQ SaaS — Setup Guide
# ================================

## Architecture Overview

```
User → Landing Page (SaaS Layer) → Signs up → Email with magic link
                                             ↓
                              DeployIQ Agent (Railway) ← token validated
                                             ↓
                              Lemon Squeezy Checkout ← upgrade flow
                                             ↓
                              Webhook → upgrade DB → send access email
```

## Files Overview

| File | Purpose |
|------|---------|
| `saas_main.py` | Main FastAPI app — all SaaS endpoints |
| `saas_database.py` | Neon PostgreSQL — users & usage tables |
| `saas_email.py` | SMTP email system — all 4 email templates |
| `saas_scheduler.py` | Background job — trial expiry emails |
| `saas_admin.py` | Admin dashboard — user stats |
| `saas_middleware.py` | Add to DeployIQ agent to enforce token auth |
| `templates/landing.html` | Production landing page |
| `templates/success.html` | Post-payment success page |
| `.env.example` | All environment variables |
| `railway.toml` | Railway deployment config |

---

## Step 1: Neon Database Setup

1. Go to https://neon.tech → Create free account
2. Create new project → copy the **Connection String**
3. It looks like: `postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`
4. Set as `DATABASE_URL` in Railway env vars
5. Tables are auto-created on first startup ✓

---

## Step 2: Gmail SMTP Setup

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** (required)
3. Search for **App Passwords** → Create one for "Mail"
4. Copy the 16-character password (no spaces)
5. Set in env:
   ```
   SMTP_USER=youremail@gmail.com
   SMTP_PASSWORD=xxxxxxxxxxxx
   ```

> **Alternative**: Use any SMTP provider (Mailgun, SendGrid, Resend)
> Just change SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

---

## Step 3: Lemon Squeezy Setup

### Create Product
1. Go to https://app.lemonsqueezy.com → Products → New Product
2. Name: "DeployIQ Forever"
3. Price: $29.99 (one-time)
4. After creating, copy the **Checkout URL**
   Format: `https://yourstore.lemonsqueezy.com/checkout/buy/xxxxxxxx`

### Configure Webhook
1. Settings → Webhooks → Add Webhook
2. URL: `https://your-saas.railway.app/webhook/lemon-squeezy`
3. Events to subscribe: `order_created`
4. Copy the **Signing Secret** → set as `LEMON_SQUEEZY_WEBHOOK_SECRET`

---

## Step 4: Railway Deployment

### Deploy SaaS Layer
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Create new project
railway new

# Link to repo (or use GitHub deployment)
railway link

# Set environment variables (copy from .env.example)
railway variables set DATABASE_URL="postgresql://..."
railway variables set JWT_SECRET="your-32-char-secret"
railway variables set LEMON_SQUEEZY_WEBHOOK_SECRET="..."
railway variables set LEMON_SQUEEZY_STORE_URL="https://..."
railway variables set SMTP_USER="your@gmail.com"
railway variables set SMTP_PASSWORD="your-app-password"
railway variables set DEPLOYIQ_AGENT_URL="https://your-agent.railway.app"
railway variables set FRONTEND_URL="https://your-saas.railway.app"

# Deploy
railway up
```

### Add Middleware to DeployIQ Agent
In your existing `main.py` (DeployIQ agent), add:

```python
# At the top, after other imports
from saas_middleware import SaaSAuthMiddleware

# After creating the app, before routes
app.add_middleware(SaaSAuthMiddleware)
```

Also add to your agent's Railway env vars:
```
SAAS_API_URL=https://your-saas.railway.app
JWT_SECRET=same-secret-as-saas-layer
```

---

## Step 5: Add Admin Router (Optional)

In `saas_main.py`, add at the bottom:

```python
from saas_admin import router as admin_router
app.include_router(admin_router)
```

Access at: `https://your-saas.railway.app/admin?key=YOUR_ADMIN_KEY`

---

## Step 6: Run Trial Expiry Scheduler

### Option A: Separate Railway service
```bash
railway service add
# Start command: python saas_scheduler.py
```

### Option B: Add to main app lifespan
In `saas_main.py` lifespan function:
```python
import asyncio
from saas_scheduler import run_expiry_checks

@asynccontextmanager
async def lifespan(app):
    await init_saas_db()
    # Start scheduler in background
    task = asyncio.create_task(scheduler_loop_bg())
    yield
    task.cancel()
    await close_saas_pool()

async def scheduler_loop_bg():
    while True:
        try:
            await run_expiry_checks()
        except Exception as e:
            logger.error(f"Scheduler: {e}")
        await asyncio.sleep(3600)
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | Neon PostgreSQL connection string |
| `JWT_SECRET` | ✅ | 32+ char random string for token signing |
| `DEPLOYIQ_AGENT_URL` | ✅ | URL of your DeployIQ Railway deployment |
| `FRONTEND_URL` | ✅ | URL of this SaaS layer |
| `LEMON_SQUEEZY_WEBHOOK_SECRET` | ✅ | From Lemon Squeezy webhook settings |
| `LEMON_SQUEEZY_STORE_URL` | ✅ | Your checkout page URL |
| `SMTP_USER` | ✅ | Gmail address |
| `SMTP_PASSWORD` | ✅ | Gmail App Password (16 chars) |
| `SMTP_HOST` | ⚪ | Default: smtp.gmail.com |
| `SMTP_PORT` | ⚪ | Default: 587 |
| `TRIAL_DAYS` | ⚪ | Default: 7 |
| `TRIAL_MAX_REPORTS` | ⚪ | Default: 2 |
| `ADMIN_KEY` | ⚪ | Protect /admin endpoint |
| `ENV` | ⚪ | Set to "production" to hide /docs |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page |
| POST | `/signup` | Create trial or forever account |
| GET | `/verify-token?token=xxx` | Validate token + redirect to agent |
| GET | `/user-status` | Get user plan/usage status |
| POST | `/generate-report` | Gate check before report generation |
| POST | `/webhook/lemon-squeezy` | Payment webhook |
| GET | `/upgrade?email=xxx` | Redirect to Lemon Squeezy checkout |
| GET | `/success` | Post-payment success page |
| GET | `/admin?key=xxx` | Admin dashboard |
| GET | `/health` | Health check |

---

## User Flow

### Trial Flow
1. User visits landing page
2. Clicks "Try 7 Days Free" → email popup
3. `POST /signup` → creates user → sends trial email
4. User clicks link in email → `GET /verify-token`
5. Redirect to DeployIQ agent with token
6. SaaSAuthMiddleware validates token on each /evaluate call
7. After 2 reports OR 7 days → 402 response with upgrade URL

### Payment Flow
1. User clicks "Upgrade Now" in expired message or email
2. Redirect to Lemon Squeezy checkout with pre-filled email
3. User pays → Lemon Squeezy fires webhook
4. `POST /webhook/lemon-squeezy` → upgrades user in DB
5. Sends payment success email with access link
6. User now has unlimited reports

### Forever Plan Flow
1. User clicks "Forever Plan" on landing page
2. Enters email → POST /signup with plan=forever
3. Redirect to Lemon Squeezy checkout
4. Same payment flow as above
