# main.py — DeployIQ v3.1 (Production-Ready)
from dotenv import load_dotenv
load_dotenv()  
import os
import io
import uuid
import time
import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from database import init_db, log_request, update_request_status, close_pool
from evaluator import evaluate_model
from risk_engine import assess_risk
from pdf_generator import generate_pdf
from file_parser import parse_file, SUPPORTED_EXTENSIONS

# ── Logging with rotation (fix #15) ───────────────────────────────────────────
_file_handler = logging.handlers.RotatingFileHandler(
    "deployiq.log", maxBytes=10 * 1024 * 1024, backupCount=3
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[_file_handler, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ── Sentry — 10% sample rate in production (fix #14) ──────────────────────────
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.1,   # was 1.0 — would blow free tier
    )
    logger.info("Sentry monitoring enabled")

# ── Config ─────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB    = int(os.getenv("MAX_FILE_SIZE_MB", 20))
MAX_FILE_SIZE       = MAX_FILE_SIZE_MB * 1024 * 1024
PROCESSING_TIMEOUT  = int(os.getenv("PROCESSING_TIMEOUT", 90))
ADMIN_KEY           = os.getenv("ADMIN_KEY", "")          # fix #9
TEMP_DIR            = "temp_files"
ACCEPTED_EXTENSIONS_STR = ", ".join(sorted(SUPPORTED_EXTENSIONS))


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Fix #4 — clean up any leftover temp files from previous crashed run
    _purge_stale_temps()

    await init_db()                          # fix #2 — properly awaited
    logger.info("DeployIQ started ✓  (PostgreSQL pool ready)")
    yield

    await close_pool()
    logger.info("DeployIQ shutdown — pool closed")


# ── App ────────────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])

app = FastAPI(
    title="DeployIQ",
    description="AI Model Deployment Risk Validator",
    version="3.1.0",
    lifespan=lifespan,
    # Hide internal details from OpenAPI docs in production
    docs_url=None if os.getenv("ENV") == "production" else "/docs",
    redoc_url=None if os.getenv("ENV") == "production" else "/redoc",
)

# Fix #7 — CORS middleware
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


# ── Auth dependency for admin endpoints (fix #9) ──────────────────────────────
def require_admin(request: Request):
    if not ADMIN_KEY:
        return   # no key set → open (dev mode)
    key = request.headers.get("X-Admin-Key") or request.query_params.get("key")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── robots.txt (fix #16) ───────────────────────────────────────────────────────
@app.get("/robots.txt", include_in_schema=False)
async def robots():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        "User-agent: *\nDisallow: /evaluate\nDisallow: /stats\nDisallow: /health\n"
    )


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status":    "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version":   "3.1.0",
    }


# ── Stats — admin-only (fix #9) ────────────────────────────────────────────────
@app.get("/stats")
async def stats(_: None = Depends(require_admin)):
    from database import get_stats
    return await get_stats()


# ── Status polling endpoint (fix #10) ─────────────────────────────────────────
_job_status: dict[str, dict] = {}   # in-memory; fine for single-node

@app.get("/status/{job_id}")
async def job_status(job_id: str):
    info = _job_status.get(job_id)
    if not info:
        raise HTTPException(status_code=404, detail="Job not found")
    return info


# ── Home ───────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Evaluate ───────────────────────────────────────────────────────────────────
@app.post("/evaluate")
@limiter.limit("10/minute")
async def evaluate(request: Request, file: UploadFile = File(...)):

    unique_id  = str(uuid.uuid4())
    client_ip  = get_remote_address(request)
    start_time = time.time()

    # Fix #3 — sanitise filename to prevent path traversal
    raw_name = file.filename or "upload"
    filename = os.path.basename(raw_name).replace("..", "").strip() or "upload"
    ext      = os.path.splitext(filename.lower())[1]

    # Fix #12 — timestamped PDF filename
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pdf_download_name = f"DeployIQ_Report_{ts}.pdf"

    # ── 1. Extension validation ────────────────────────────────────────────────
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted: {ACCEPTED_EXTENSIONS_STR}",
        )

    # ── 2. Stream file into memory (fix #6 — no disk race condition) ──────────
    file_bytes = io.BytesIO()
    file_size  = 0
    try:
        while chunk := await file.read(65536):
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB.",
                )
            file_bytes.write(chunk)
    except HTTPException:
        raise

    file_bytes.seek(0)
    logger.info(f"[{unique_id}] Received: {filename} ({file_size/1024:.1f}KB) from {client_ip}")

    # ── 3. Log to PostgreSQL (fix #1 — properly awaited) ──────────────────────
    await log_request(unique_id, filename, file_size, client_ip, file_type=ext.lstrip("."))

    # ── 4. Update status to 'processing' for polling (fix #10) ───────────────
    _job_status[unique_id] = {"status": "processing", "progress": "Parsing file..."}

    # ── 5. Process with timeout ────────────────────────────────────────────────
    try:
        pdf_bytes, metrics, risk_data = await asyncio.wait_for(
            _process_file(file_bytes, filename, unique_id),
            timeout=PROCESSING_TIMEOUT,
        )
    except asyncio.TimeoutError:
        _job_status.pop(unique_id, None)
        await update_request_status(unique_id, "timeout")   # fix #1
        logger.error(f"[{unique_id}] Timed out after {PROCESSING_TIMEOUT}s")
        raise HTTPException(status_code=408, detail="Processing timed out. Try a smaller file.")
    except ValueError as e:
        _job_status.pop(unique_id, None)
        await update_request_status(unique_id, f"error: {str(e)[:100]}")   # fix #1
        logger.warning(f"[{unique_id}] Validation error: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        _job_status.pop(unique_id, None)
        await update_request_status(unique_id, f"error: internal")         # fix #11
        logger.error(f"[{unique_id}] Unexpected error: {e}", exc_info=True)
        if SENTRY_DSN:
            sentry_sdk.capture_exception(e)
        # Fix #11 — never expose internal details to user
        raise HTTPException(status_code=500, detail="Report generation failed. Our team has been notified.")

    elapsed = time.time() - start_time
    await update_request_status(                               # fix #1
        unique_id, "success",
        task_type=metrics.get("task_type"),
        risk_level=risk_data.get("risk_level"),
        processing_time=round(elapsed, 2),
    )
    _job_status.pop(unique_id, None)
    logger.info(
        f"[{unique_id}] Done in {elapsed:.2f}s — "
        f"Risk: {risk_data.get('risk_level')} | Type: {metrics.get('task_type')}"
    )

    # Fix #6 — stream PDF from memory, no temp file needed
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_download_name}"'},
    )


# ── Helpers ────────────────────────────────────────────────────────────────────
async def _process_file(file_bytes: io.BytesIO, filename: str, job_id: str):
    """Parse, evaluate, assess risk, generate PDF — all in thread pool."""
    loop = asyncio.get_event_loop()

    # Step 1 — parse
    _job_status[job_id] = {"status": "processing", "progress": "Parsing file..."}
    df, _ftype = await loop.run_in_executor(None, parse_file_bytes, file_bytes, filename)

    # Step 2 — evaluate
    _job_status[job_id] = {"status": "processing", "progress": "Computing metrics..."}
    metrics = await loop.run_in_executor(None, evaluate_model, df)

    # Fix #13 — sanity check: make sure we got real metrics back
    if metrics.get("dataset_size", 0) < 2:
        raise ValueError("File does not appear to contain valid model prediction data.")

    # Step 3 — risk assessment
    _job_status[job_id] = {"status": "processing", "progress": "Assessing risk..."}
    risk_data = await loop.run_in_executor(None, assess_risk, metrics)

    # Step 4 — generate PDF into memory (fix #6)
    _job_status[job_id] = {"status": "processing", "progress": "Generating report..."}
    pdf_bytes = await loop.run_in_executor(None, generate_pdf_bytes, metrics, risk_data)

    return pdf_bytes, metrics, risk_data


def parse_file_bytes(file_bytes: io.BytesIO, filename: str):
    """Write bytes to a named temp file so file_parser can detect extension, then clean up."""
    import tempfile, os
    ext = os.path.splitext(filename.lower())[1]
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes.read())
        tmp_path = tmp.name
    try:
        return parse_file(tmp_path, filename)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def generate_pdf_bytes(metrics, risk_data) -> bytes:
    """Generate PDF into memory and return raw bytes (fix #6)."""
    buf = io.BytesIO()
    generate_pdf(metrics, risk_data, buf)
    buf.seek(0)
    return buf.read()


def _purge_stale_temps():
    """Delete any temp files left over from a previous crash (fix #4)."""
    try:
        cutoff = time.time() - 600   # older than 10 minutes
        for fname in os.listdir(TEMP_DIR):
            fpath = os.path.join(TEMP_DIR, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    logger.info(f"Purged stale temp file: {fname}")
            except Exception:
                pass
    except Exception:
        pass
