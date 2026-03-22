# saas_middleware.py — Token validation middleware for DeployIQ agent
# Add this to your main.py (the AI agent) to enforce SaaS limits

import os
import hmac
import hashlib
import logging
import httpx
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

SAAS_API_URL = os.getenv("SAAS_API_URL", "")       # URL of the SaaS layer
JWT_SECRET   = os.getenv("JWT_SECRET", "")
BYPASS_PATHS = {"/health", "/", "/robots.txt", "/docs", "/redoc", "/openapi.json"}


class SaaSAuthMiddleware(BaseHTTPMiddleware):
    """
    Validates tokens on /evaluate endpoint.
    Checks trial limits via the SaaS API before allowing report generation.
    
    Usage in main.py:
        from saas_middleware import SaaSAuthMiddleware
        app.add_middleware(SaaSAuthMiddleware)
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip non-protected paths
        if path in BYPASS_PATHS or not path.startswith("/evaluate"):
            return await call_next(request)

        # Extract token
        token = (
            request.query_params.get("token")
            or request.headers.get("X-Access-Token")
            or request.cookies.get("deployiq_token")
        )

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error":       "No access token provided.",
                    "signup_url":  f"{SAAS_API_URL}/",
                    "message":     "Sign up at DeployIQ to get your access token.",
                }
            )

        # Verify token locally (fast path)
        decoded = self._verify_token(token)
        if not decoded:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or expired access token."}
            )

        # Check limits with SaaS API
        if SAAS_API_URL:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.post(
                        f"{SAAS_API_URL}/generate-report",
                        headers={"X-Access-Token": token},
                    )
                    if res.status_code == 402:
                        data = res.json()
                        return JSONResponse(
                            status_code=402,
                            content={
                                "error":       data.get("message", "Trial expired."),
                                "checkout_url": data.get("checkout_url", ""),
                                "upgrade_url": f"{SAAS_API_URL}/upgrade",
                            }
                        )
                    elif res.status_code not in (200, 201):
                        logger.warning(f"SaaS gate returned {res.status_code}")
                        # Fail open in case SaaS is down (prevents disruption)
            except Exception as e:
                logger.warning(f"SaaS gate unreachable: {e} — failing open")

        # Attach user info to request state
        request.state.user_id = decoded.get("user_id")
        request.state.email   = decoded.get("email")

        return await call_next(request)

    @staticmethod
    def _verify_token(token: str) -> dict | None:
        try:
            import base64
            raw   = base64.urlsafe_b64decode(token.encode()).decode()
            parts = raw.split(":")
            if len(parts) != 4:
                return None
            user_id, email, nonce, sig = parts
            payload  = f"{user_id}:{email}:{nonce}"
            expected = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            return {"user_id": user_id, "email": email}
        except Exception:
            return None
