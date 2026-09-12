# dizercoreai.py  
# DizerCore.AI — Pi-hosted multi-agent code pipeline (modular entrypoint).  
# Pipeline: OpenRouter (generate, tier-rotation) -> Groq (verify) -> Gemini (final cleaned code)  
# Each stage has a safetywall (rechecks its own output, retries on junk) and a  
# per-stage confidence score. Complexity (1-5) is user-set and picks each stage's model tier.  
import asyncio  
import logging  
import os  
from contextlib import asynccontextmanager  
from logging.handlers import RotatingFileHandler  
  
import httpx  
from fastapi import FastAPI  
from fastapi.staticfiles import StaticFiles  
from google import genai  
  
import config  
import db  
import runtime  
import providers  
from routes import router  
  
# ---------------------------------------------------------------------------  
# Logging (console + rotating file; guarded so re-import doesn't stack handlers)  
# ---------------------------------------------------------------------------  
logger = logging.getLogger("DizerCore")  
logger.setLevel(logging.INFO)  
if not logger.handlers:  
    _fmt = logging.Formatter("%(asctime)s %(levelname)s [DizerCore] %(message)s")  
    _sh = logging.StreamHandler()  
    _sh.setFormatter(_fmt)  
    logger.addHandler(_sh)  
    _fh = RotatingFileHandler(config.LOG_FILE, maxBytes=2_000_000, backupCount=3)  
    _fh.setFormatter(_fmt)  
    logger.addHandler(_fh)  
  
  
# ---------------------------------------------------------------------------  
# Lifespan: build shared state on runtime.* and hand it to every module  
# ---------------------------------------------------------------------------  
@asynccontextmanager  
async def lifespan(app: FastAPI):  
    # Load + validate API keys (raises clearly if any are missing).  
    runtime.cfg = config.Config.from_env()  
  
    # Create the persistent DB tables (users / jobs / sessions).  
    db.init_users_db()  
    db.init_jobs_db()  
    db.init_sessions_db()  
  
    # Restore history + live sessions from the SSD so they survive restarts.  
    runtime.JOBS = db.load_jobs()  
    runtime.SESSIONS = db.load_sessions()  
  
    # Shared clients + concurrency guard, all on runtime.* (providers reads these).  
    runtime.gemini_client = genai.Client(api_key=runtime.cfg.gemini_key)  
    runtime.http_client = httpx.AsyncClient(timeout=120)  
    runtime.job_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)  
  
    logger.info(  
        "DizerCore startup complete; data dir=%s; %d job(s), %d session(s) loaded.",  
        config.DATA_DIR, len(runtime.JOBS), len(runtime.SESSIONS),  
    )  
    try:  
        yield  
    finally:  
        await runtime.http_client.aclose()  
        logger.info("DizerCore shutdown; HTTP client closed.")  
  
  
app = FastAPI(lifespan=lifespan)  
  
# ---------------------------------------------------------------------------  
# Static files (serves the logo at /static/dizercore.png, used by web.py)  
# ---------------------------------------------------------------------------  
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")  
os.makedirs(_STATIC_DIR, exist_ok=True)  
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")  
  
# All route handlers live in routes.py (auth, /run, /jobs, /status, /stop, favicon).  
app.include_router(router)  
  
  
if __name__ == "__main__":  
    import uvicorn  
    port = int(os.environ.get("PORT", "8000"))  
    uvicorn.run(app, host="0.0.0.0", port=port)
