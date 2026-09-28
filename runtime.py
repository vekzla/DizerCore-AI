# DizerCore-AI  
# ----------------------------------------------------------------------------  
# runtime.py — mutable shared state, populated at startup by the FastAPI  
# lifespan handler (see dizercoreai.py). Kept in its own module so every other  
# module can read it WITHOUT circular imports — runtime.py imports nothing  
# from the app.  
cfg = None            # config.Config instance (holds the API keys, incl. judge_key)  
gemini_client = None  # google.genai client  
http_client = None    # httpx.AsyncClient  
job_semaphore = None  # asyncio.Semaphore(MAX_CONCURRENT_JOBS)  
  
JOBS = {}      # job_id -> db.Job  
TASKS = {}     # job_id -> asyncio.Task (for cancellation)  
SESSIONS = {}  # cookie token -> username  
ATTACH = {}    # job_id -> [{name, kind, mime, data}] binary uploads for providers
