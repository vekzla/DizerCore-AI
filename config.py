# DizerCore-AI  
# ----------------------------------------------------------------------------  
# config.py — configuration, constants, model tiers, and shared predicates.  
import logging  
import os  
from dataclasses import dataclass  
from logging.handlers import RotatingFileHandler  
  
# ---------------------------------------------------------------------------  
# Paths (all persistent data lives on the SSD, set via DIZER_DATA_DIR)  
# ---------------------------------------------------------------------------  
DATA_DIR = os.environ.get("DIZER_DATA_DIR", "/mnt/dizerdata/dizercore")  
os.makedirs(DATA_DIR, exist_ok=True)  
USERS_DB = os.path.join(DATA_DIR, "dizer_users.db")  
JOBS_DB = os.path.join(DATA_DIR, "dizer_jobs.db")  
SESSIONS_DB = os.path.join(DATA_DIR, "dizer_sessions.db")  
LOG_FILE = os.path.join(DATA_DIR, "dizercore.log")  
  
# ---------------------------------------------------------------------------  
# Logging — INFO to console + rotating file on the SSD  
# ---------------------------------------------------------------------------  
logger = logging.getLogger("DizerCore")  
if not logger.handlers:  
    logger.setLevel(logging.INFO)  
    _fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")  
    _ch = logging.StreamHandler(); _ch.setFormatter(_fmt)  
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)  
    _fh.setFormatter(_fmt)  
    logger.addHandler(_ch); logger.addHandler(_fh)  
  
VERSION = "1.0.0"  
SERVICE_NAME = "dizercore"  
  
# ---------------------------------------------------------------------------  
# Limits / tuning  
# ---------------------------------------------------------------------------  
MAX_PROMPT_CHARS = int(os.environ.get("MAX_PROMPT_CHARS", "20000"))  
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", "2000000"))        # 2 MB/file  
MAX_TOTAL_FILE_BYTES = int(os.environ.get("MAX_TOTAL_FILE_BYTES", "8000000"))  
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))  
  
RATE_LIMIT_DELAY = float(os.environ.get("RATE_LIMIT_DELAY", "2"))  
# Serial delay BEFORE every judge call — keeps the dedicated judge key under  
# free-tier per-minute limits.  
JUDGE_DELAY = float(os.environ.get("JUDGE_DELAY", "5"))  
  
WEBUI_ADMIN_PASSWORD = os.environ.get("WEBUI_ADMIN_PASSWORD", "")  
  
# ---------------------------------------------------------------------------  
# Username / password rules (username min 5, password min 8)  
# ---------------------------------------------------------------------------  
MIN_USERNAME_LEN = 5  
MIN_PASSWORD_LEN = 8  
  
# ---------------------------------------------------------------------------  
# Model tiers — ONE tier per job picked by complexity.  
# ---------------------------------------------------------------------------  
def _list_from_env(var: str, default: list) -> list:  
    raw = os.environ.get(var, "")  
    if not raw.strip():  
        return list(default)  
    return [s.strip() for s in raw.split(",") if s.strip()]  
  
  
def _tier_map(prefix: str, light: list, normal: list, heavy: list) -> dict:  
    return {  
        "light": _list_from_env(prefix + "_LIGHT", light),  
        "normal": _list_from_env(prefix + "_NORMAL", normal),  
        "heavy": _list_from_env(prefix + "_HEAVY", heavy),  
    }  
  
  
# OpenRouter — 3 slugs per tier. 'inkling' models may 403 ("agentic harnesses  
# only") on a plain API key; the safetywall rotation tolerates that.  
OPENROUTER_MODELS_BY_TIER = _tier_map(  
    "OPENROUTER_MODEL",  
    light=[  
        "poolside/laguna-xs-2.1:free",  
        "cohere/north-mini-code:free",  
        "thinkingmachines/inkling-small:free",  
    ],  
    normal=[  
        "poolside/laguna-s-2.1:free",  
        "thinkingmachines/inkling:free",  
        "qwen/qwen3.8-27b:free",  
    ],  
    heavy=[  
        "nvidia/nemotron-3-super-120b-a12b:free",  
        "nvidia/nemotron-3-ultra-550b-a55b:free",  
        "google/gemma-4-31b-it:free",  
    ],  
)  
  
GROQ_MODELS_BY_TIER = _tier_map(  
    "GROQ_MODEL",  
    light=["llama-3.1-8b-instant"],  
    normal=["llama-3.3-70b-versatile"],  
    heavy=["llama-3.3-70b-versatile"],  
)  
  
GEMINI_MODELS_BY_TIER = _tier_map(  
    "GEMINI_MODEL",  
    light=["gemini-2.0-flash-lite"],  
    normal=["gemini-2.0-flash"],  
    heavy=["gemini-2.5-pro"],  
)  
  
# ---------------------------------------------------------------------------  
# Judge pool — scores each candidate 0-100, FIRST usable score wins.  
# Ordered best-first; pipeline rotates the start index per candidate.  
# ---------------------------------------------------------------------------  
JUDGE_MODELS = _list_from_env(  
    "JUDGE_MODELS",  
    [  
        "google/gemma-4-26b-a4b-it:free",  
        "dots-studio/dots-3-note-preview:free",  
        "liquid/lfm-2.5-2.6b:free",  
        # "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # pending endpoint test  
    ],  
)  
JUDGE_FALLBACK_MODELS = _list_from_env("JUDGE_FALLBACK_MODELS", [])  
  
# Legacy stage-toggle name kept for job.stages["inkling"].  
INKLING_MODEL = "thinkingmachines/inkling-small:free"  
  
# ---------------------------------------------------------------------------  
# Vision-capable slugs — accept image/PDF input. Used to route jobs that  
# include binary attachments; text-only slugs get a note instead.  
# ---------------------------------------------------------------------------  
VISION_MODELS = {  
    "google/gemma-4-31b-it:free",  
    "google/gemma-4-26b-a4b-it:free",  
    "dots-studio/dots-3-note-preview:free",  
    # "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # if endpoint test passes  
}  
  
# ---------------------------------------------------------------------------  
# Shared predicates  
# ---------------------------------------------------------------------------  
def tier_for(complexity: int) -> str:  
    """Complexity 1-2 -> light, 3 -> normal, 4-5 -> heavy."""  
    if complexity <= 2:  
        return "light"  
    if complexity <= 3:  
        return "normal"  
    return "heavy"  
  
  
def _is_unusable(text: str) -> bool:  
    """Safetywall predicate: True if a generation output is junk."""  
    t = (text or "").strip()  
    if len(t) < 40:  
        return True  
    if t.startswith("["):  # provider error / skipped note  
        return True  
    return False  
  
  
# ---------------------------------------------------------------------------  
# File-type routing for uploads  
# ---------------------------------------------------------------------------  
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}  
PDF_EXTS = {".pdf"}  
DOCX_EXTS = {".docx"}  
# Everything else is treated as text/code (incl. .sql .cpp .h .py .txt .md ...)  
  
  
def classify_upload(filename: str) -> str:  
    """Return 'image' | 'pdf' | 'docx' | 'text' for a filename."""  
    ext = os.path.splitext(filename or "")[1].lower()  
    if ext in IMAGE_EXTS:  
        return "image"  
    if ext in PDF_EXTS:  
        return "pdf"  
    if ext in DOCX_EXTS:  
        return "docx"  
    return "text"  
  
  
# ---------------------------------------------------------------------------  
# Runtime config — loaded once at startup into runtime.cfg  
# ---------------------------------------------------------------------------  
@dataclass  
class Config:  
    gemini_key: str  
    openrouter_key: str        # generation key (OPENROUTER_API_KEY_CODER)  
    groq_key: str  
    judge_key: str             # dedicated key for the judge pool  
  
    @staticmethod  
    def from_env() -> "Config":  
        missing = [k for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY_CODER", "GROQ_API_KEY")  
                   if not os.environ.get(k)]  
        if missing:  
            raise RuntimeError(  
                f"Missing required environment variables: {', '.join(missing)}")  
        # Judge key is optional: falls back to the generation key so existing  
        # installs keep working until a second key is provided.  
        return Config(  
            gemini_key=os.environ["GEMINI_API_KEY"],  
            openrouter_key=os.environ["OPENROUTER_API_KEY_CODER"],  
            groq_key=os.environ["GROQ_API_KEY"],  
            judge_key=os.environ.get("OPENROUTER_API_KEY_JUDGE")  
                      or os.environ["OPENROUTER_API_KEY_CODER"],  
        )
