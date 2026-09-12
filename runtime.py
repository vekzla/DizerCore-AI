# runtime.py  
# Mutable shared state, populated at startup by the FastAPI lifespan handler  
# (see routes.py). Kept in its own module so every other module can read it  
# WITHOUT circular imports — runtime.py imports nothing from the app.  
cfg = None            # config.Config instance (holds the API keys)  
gemini_client = None  # google.genai client  
http_client = None    # httpx.AsyncClient  
job_semaphore = None  # asyncio.Semaphore(MAX_CONCURRENT_JOBS)  
  
JOBS = {}      # job_id -> db.Job  
TASKS = {}     # job_id -> asyncio.Task (for cancellation)  
SESSIONS = {}  # cookie token -> username