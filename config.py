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
  
# Seconds between outbound calls — keeps free-tier keys under their RPM/RPD.  
RATE_LIMIT_DELAY = float(os.environ.get("DIZER_RATE_LIMIT_DELAY", "1.0"))  
JUDGE_DELAY = float(os.environ.get("DIZER_JUDGE_DELAY", "1.0"))  
RETRY_DELAY = float(os.environ.get("DIZER_RETRY_DELAY", "2.0"))  
  
# Admin password for the web UI (empty = no password required).  
WEBUI_ADMIN_PASSWORD = os.environ.get("WEBUI_ADMIN_PASSWORD", "")  
  
# ---------------------------------------------------------------------------  
# Model tiers — comma-separated env overrides, first live slug wins,  
# rotating through the whole list on 401/402/403/429 or junk output.  
# ---------------------------------------------------------------------------  
def _slugs(env_name: str, default: str) -> list[str]:  
    raw = os.environ.get(env_name, default)  
    return [s.strip() for s in raw.split(",") if s.strip()]  
  
  
# ---- ChatGPT (OpenAI) — the coding agent. Slugs from the account's  
# free-tier catalog; every model is capped at 50 RPD so deep lists are  
# failover runway, not ceremony. ----  
OPENAI_MODELS_BY_TIER = {  
    "light":  _slugs(  
        "OPENAI_MODEL_LIGHT",  
        "gpt-5.4-mini,gpt-5.4-nano,gpt-4o-mini,gpt-5-nano,gpt-5-mini"),  
    "normal": _slugs(  
        "OPENAI_MODEL_NORMAL",  
        "gpt-6-luna,gpt-5.6-luna,gpt-5.4,gpt-4.1,gpt-5.2"),  
    "heavy":  _slugs(  
        "OPENAI_MODEL_HEAVY",  
        "gpt-5.5-pro,gpt-5.5,gpt-5.2-pro,gpt-5.3-codex"),  
}  
  
GROQ_MODELS_BY_TIER = {  
    "light":  _slugs("GROQ_MODEL_LIGHT",  
                     "allam-2-7b,openai/gpt-oss-20b,qwen/qwen3.8-27b"),  
    "normal": _slugs("GROQ_MODEL_NORMAL",  
                     "qwen/qwen3.8-27b,openai/gpt-oss-20b,openai/gpt-oss-120b"),  
    "heavy":  _slugs("GROQ_MODEL_HEAVY",  
                     "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b"),  
}  
  
GEMINI_MODELS_BY_TIER = {  
    "light":  _slugs("GEMINI_MODEL_LIGHT",  
                     "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemma-4-26b"),  
    "normal": _slugs("GEMINI_MODEL_NORMAL",  
                     "gemini-3.8-flash,gemini-3.6-flash,gemini-3.7-flash,"  
                     "gemini-3.5-flash,gemini-3.1-flash-lite"),  
    "heavy":  _slugs("GEMINI_MODEL_HEAVY",  
                     "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,"  
                     "gemma-4-31b"),  
}  
  
# ---------------------------------------------------------------------------  
# Judge pool — OpenRouter ONLY. Every slug here accepts  
# reasoning:{"enabled":true}; providers._judge_once sends it unconditionally.  
# ---------------------------------------------------------------------------  
JUDGE_MODELS = _slugs(  
    "JUDGE_MODELS",  
    "nvidia/nemotron-3-ultra-550b-a55b:free,"  
    "nvidia/nemotron-3-super-120b-a12b:free,"  
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,"  
    "google/gemma-4-31b-it:free,"  
    "thinkingmachines/inkling:free,"  
    "qwen/qwen3.8-27b:free",  
)  
JUDGE_FALLBACK_MODELS = _slugs(  
    "JUDGE_FALLBACK_MODELS",  
    "google/gemma-4-26b-a4b-it:free,"  
    "cohere/north-mini-code:free,"  
    "nvidia/nemotron-3.5-lightning:free,"  
    "meta-llama/llama-3.3-70b-instruct:free",  
)  
  
# ---------------------------------------------------------------------------  
# Vision-capable slugs — SUBSTRING markers matched against full slugs.  
# All gpt-4o/4.1/5.x/6.x chat models take image inputs; gemini/gemma are  
# natively multimodal. Groq is text-only and gets a note instead.  
# ---------------------------------------------------------------------------  
VISION_MODELS = _slugs(  
    "VISION_MODELS",  
    "gemini,gemma,gpt-4o,gpt-4.1,gpt-5,gpt-6,qwen3-vl,vision,llava",  
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
    if mime.startswith("image/") or ext in ("png", "jpg", "jpeg", "gif",  
                                            "webp", "bmp"):  
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
    openai_key: str            # ChatGPT coder key (OPENAI_API_KEY)  
    groq_key: str  
    judge_key: str             # OpenRouter — judge pool ONLY  
  
    @staticmethod  
    def from_env() -> "Config":  
        missing = [k for k in ("GEMINI_API_KEY", "OPENAI_API_KEY",  
                               "GROQ_API_KEY", "OPENROUTER_API_KEY_JUDGE")  
                   if not os.environ.get(k)]  
        if missing:  
            raise RuntimeError(  
                f"Missing required environment variables: {', '.join(missing)}")  
        return Config(  
            gemini_key=os.environ["GEMINI_API_KEY"],  
            openai_key=os.environ["OPENAI_API_KEY"],  
            groq_key=os.environ["GROQ_API_KEY"],  
            judge_key=os.environ["OPENROUTER_API_KEY_JUDGE"],  
        )
