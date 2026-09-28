# DizerCore-AI    
# ----------------------------------------------------------------------------    
# dizercoreai.py — entrypoint: builds the FastAPI app, runs lifespan startup    
# (loads keys, opens DBs, restores jobs/sessions, creates shared clients),    
# mounts /static, and starts uvicorn.    
import asyncio    
import logging    
import os    
from contextlib import asynccontextmanager    
  
import httpx    
from fastapi import FastAPI    
from fastapi.staticfiles import StaticFiles    
from google import genai    
  
import runtime    
from config import Config, LOG_FILE, MAX_CONCURRENT_JOBS, setup_logging    
from db import (    
    init_users_db, init_sessions_db, init_jobs_db, load_sessions, load_jobs,    
)    
from routes import router    
  
  
@asynccontextmanager    
async def lifespan(app: FastAPI):    
    setup_logging()    
    log = logging.getLogger("dizercoreai")    
    runtime.cfg = Config.from_env()    
  
    init_users_db()    
    init_sessions_db()    
    init_jobs_db()    
    runtime.SESSIONS.update(load_sessions())    
    runtime.JOBS.update(load_jobs())    
    log.info("Restored %d sessions, %d jobs.",    
             len(runtime.SESSIONS), len(runtime.JOBS))    
  
    runtime.gemini_client = genai.Client(api_key=runtime.cfg.gemini_key)    
    # No read timeout: streaming responses can run for minutes.    
    runtime.http_client = httpx.AsyncClient(    
        timeout=httpx.Timeout(120.0, read=None)    
    )    
    runtime.job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)    
    log.info("Startup complete.")    
    yield    
    await runtime.http_client.aclose()    
  
  
app = FastAPI(lifespan=lifespan)    
  
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")    
os.makedirs(_STATIC_DIR, exist_ok=True)    
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")    
  
app.include_router(router)    
  
if __name__ == "__main__":    
    import uvicorn    
    port = int(os.environ.get("PORT", "8000"))    
    uvicorn.run(app, host="0.0.0.0", port=port)
