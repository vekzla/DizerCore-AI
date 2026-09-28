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
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")  
    ch = logging.StreamHandler()  
    ch.setFormatter(fmt)  
    logger.addHandler(ch)  
    try:  
        fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)  
        fh.setFormatter(fmt)  
        logger.addHandler(fh)  
    except OSError:  
        pass  
logger.propagate = False  
  
  
def setup_logging() -> logging.Logger:  
    """Idempotent — handlers are attached at import; returns the shared logger."""  
    return logger  
  
  
# ---------------------------------------------------------------------------  
# Limits / tuning  
# ---------------------------------------------------------------------------  
MAX_PROMPT_CHARS = 8000  
MAX_FILE_BYTES = 200_000  
MAX_TOTAL_FILE_BYTES = 800_000  
MAX_TOKENS = int(os.environ.get("DIZER_MAX_TOKENS", "8192"))  
MAX_OUTPUT_TOKENS = int(os.environ.get("DIZER_MAX_OUTPUT_TOKENS", str(MAX_TOKENS)))  
GROQ_MAX_OUTPUT_TOKENS = int(os.environ.get("DIZER_GROQ_MAX_OUTPUT_TOKENS", "8192"))  
MAX_SAFETYWALL_TRIES = int(os.environ.get("DIZER_MAX_SAFETYWALL_TRIES", "8"))  
MAX_CONCURRENT_JOBS = int(os.environ.get("DIZER_MAX_CONCURRENT_JOBS", "2"))  
  
# Seconds between outbound calls — keeps the free-tier keys under their RPM.  
RATE_LIMIT_DELAY = float(os.environ.get("DIZER_RATE_LIMIT_DELAY", "1.0"))  
JUDGE_DELAY = float(os.environ.get("DIZER_JUDGE_DELAY", "1.0"))  
RETRY_DELAY = float(os.environ.get("DIZER_RETRY_DELAY", "2.0"))  
  
# Admin password for the web UI (empty = no password required).  
WEBUI_ADMIN_PASSWORD = os.environ.get("WEBUI_ADMIN_PASSWORD", "")  
  
# ---------------------------------------------------------------------------  
# Model tiers — comma-separated env overrides, first live slug wins.  
# ---------------------------------------------------------------------------  
def _slugs(env_name: str, default: str) -> list[str]:  
    raw = os.environ.get(env_name, default)  
    return [s.strip() for s in raw.split(",") if s.strip()]  
  
  
OPENROUTER_MODELS_BY_TIER = {  
    "light":  _slugs("OPENROUTER_MODEL_LIGHT",  
                     "meta-llama/llama-3.3-70b-instruct:free,qwen/qwen3-32b:free"),  
    "normal": _slugs("OPENROUTER_MODEL_NORMAL",  
                     "qwen/qwen3-32b:free,meta-llama/llama-3.3-70b-instruct:free"),  
    "heavy":  _slugs("OPENROUTER_MODEL_HEAVY",  
                     "qwen/qwen3-235b-a22b:free,deepseek/deepseek-r1:free"),  
}  
  
GROQ_MODELS_BY_TIER = {  
    "light":  _slugs("GROQ_MODEL_LIGHT",  "openai/gpt-oss-20b,allam-2-7b"),  
    "normal": _slugs("GROQ_MODEL_NORMAL", "qwen/qwen3.8-27b,openai/gpt-oss-20b"),  
    "heavy":  _slugs("GROQ_MODEL_HEAVY",  
                     "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b"),  
}  
  
GEMINI_MODELS_BY_TIER = {  
    "light":  _slugs("GEMINI_MODEL_LIGHT",  "gemini-3.5-flash-lite"),  
    "normal": _slugs("GEMINI_MODEL_NORMAL", "gemini-3.5-flash-lite,gemini-3.8-flash"),  
    "heavy":  _slugs("GEMINI_MODEL_HEAVY",  
                     "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.7-flash"),  
}  
  
# ---------------------------------------------------------------------------  
# Judge pool — OpenRouter slugs that can reliably emit SCORE:/COMMENTS:.  
# ---------------------------------------------------------------------------  
JUDGE_MODELS = _slugs(  
    "JUDGE_MODELS",  
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,"  
    "inclusionai/ling-3.0-flash-vl:free,"  
    "qwen/qwen3-32b:free",  
)  
JUDGE_FALLBACK_MODELS = _slugs(  
    "JUDGE_FALLBACK_MODELS",  
    "meta-llama/llama-3.3-70b-instruct:free",  
)  
  
# ---------------------------------------------------------------------------  
# Reasoning models — streamed *_thinking deltas shown in the dashboard.  
# ---------------------------------------------------------------------------  
_NON_REASONING = { }  # slugs to exclude (historically a dict; set() wraps it)  
  
_ALL_OPENROUTER_SLUGS = (  
    set(OPENROUTER_MODELS_BY_TIER["light"])  
    | set(OPENROUTER_MODELS_BY_TIER["normal"])  
    | set(OPENROUTER_MODELS_BY_TIER["heavy"])  
    | set(JUDGE_MODELS)  
    | set(JUDGE_FALLBACK_MODELS)  
)  
REASONING_MODELS = {  
    s for s in _ALL_OPENROUTER_SLUGS  
    if any(k in s for k in ("reasoning", "r1", "thinking", "deepseek"))  
} - set(_NON_REASONING)  
  
# ---------------------------------------------------------------------------  
# Vision-capable slugs (receive binary attachments inline)  
# ---------------------------------------------------------------------------  
VISION_MODELS = _slugs(  
    "VISION_MODELS",  
    "gemini,gemma,qwen3-vl,vision,llava",  
)  
  
  
def _is_unusable(text: str) -> bool:  
    """Safetywall: detect deflection/refusal output instead of code."""  
    if not text or not text.strip():  
        return True  
    low = text.lower()  
    deflections = (  
        "paste the code", "please provide", "could you please",  
        "share the code", "provide the code", "no code provided",  
        "no code was provided", "i don't see any code", "once i have the",  
        "as an ai", "i cannot assist", "user safety: safe",  
    )  
    return any(d in low for d in deflections)  
  
  
def classify_upload(name: str, mime: str) -> str:  
    """Return 'image', 'pdf', 'docx', or 'text' for an uploaded file."""  
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""  
    if mime.startswith("image/") or ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):  
        return "image"  
    if mime == "application/pdf" or ext == "pdf":  
        return "pdf"  
    if ext == "docx" or "wordprocessingml" in mime:  
        return "docx"  
    return "text"  
  
  
def tier_for(complexity: int) -> str:  
    """1-2 -> light, 3 -> normal, 4-5 -> heavy."""  
    if complexity <= 2:  
        return "light"  
    if complexity >= 4:  
        return "heavy"  
    return "normal"  
  
  
# ---------------------------------------------------------------------------  
# Config — API keys loaded once at startup into runtime.cfg  
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
        return Config(  
            gemini_key=os.environ["GEMINI_API_KEY"],  
            openrouter_key=os.environ["OPENROUTER_API_KEY_CODER"],  
            groq_key=os.environ["GROQ_API_KEY"],  
            judge_key=os.environ.get("OPENROUTER_API_KEY_JUDGE")  
                      or os.environ["OPENROUTER_API_KEY_CODER"],  
        )
