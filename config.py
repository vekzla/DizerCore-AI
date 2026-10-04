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
  
  
# ---- ChatGPT (OpenAI) — the coding agent. chat/completions-compatible slugs  
# ONLY: codex/responses-only models (gpt-5.3-codex etc.) return 404 here. ----  
OPENAI_MODELS_BY_TIER = {  
    "light":  _slugs(  
        "OPENAI_MODEL_LIGHT",  
        "gpt-4o-mini,gpt-4.1-mini"),  
    "normal": _slugs(  
        "OPENAI_MODEL_NORMAL",  
        "gpt-4.1,gpt-4o"),  
    "heavy":  _slugs(  
        "OPENAI_MODEL_HEAVY",  
        "gpt-4.1,o4-mini"),  
}  
  
GROQ_MODELS_BY_TIER = {  
    "light":  _slugs("GROQ_MODEL_LIGHT",  
                     "openai/gpt-oss-20b,llama-3.1-8b-instant"),  
    "normal": _slugs("GROQ_MODEL_NORMAL",  
                     "openai/gpt-oss-120b,openai/gpt-oss-20b,"  
                     "llama-3.3-70b-versatile"),  
    "heavy":  _slugs("GROQ_MODEL_HEAVY",  
                     "openai/gpt-oss-120b,llama-3.3-70b-versatile"),  
}  
  
GEMINI_MODELS_BY_TIER = {  
    "light":  _slugs("GEMINI_MODEL_LIGHT",  
                     "gemini-2.0-flash-lite,gemini-2.0-flash"),  
    "normal": _slugs("GEMINI_MODEL_NORMAL",  
                     "gemini-2.5-flash,gemini-2.0-flash"),  
    "heavy":  _slugs("GEMINI_MODEL_HEAVY",  
                     "gemini-2.5-pro,gemini-2.5-flash"),  
}  
  
# ---------------------------------------------------------------------------  
# Judge pool — OpenRouter ONLY. Every slug here accepts  
# reasoning:{"enabled":true}; providers._judge_once sends it unconditionally.  
# ---------------------------------------------------------------------------  
JUDGE_MODELS = _slugs(  
    "JUDGE_MODELS",  
    "nvidia/nemotron-3-nano-30b-a3b:free,"  
    "meta-llama/llama-3.3-70b-instruct:free,"  
    "qwen/qwen3-32b:free,"  
    "google/gemma-3-27b-it:free",  
)  
JUDGE_FALLBACK_MODELS = _slugs(  
    "JUDGE_FALLBACK_MODELS",  
    "meta-llama/llama-3.3-70b-instruct:free,"  
    "google/gemma-3-12b-it:free,"  
    "mistralai/mistral-small-3.1-24b-instruct:free",  
)  
  
# ---------------------------------------------------------------------------  
# Vision-capable slugs — SUBSTRING markers matched against full slugs.  
# All gpt-4o/4.1 chat models take image inputs; gemini/gemma are natively  
# multimodal. Groq is text-only and gets a note instead.  
# ---------------------------------------------------------------------------  
VISION_MODELS = _slugs(  
    "VISION_MODELS",  
    "gemini,gemma,gpt-4o,gpt-4.1,gpt-5,qwen3-vl,vision,llava",  
)  
  
# ---------------------------------------------------------------------------  
# Two-Pi build executor — edith -> tadashi over SSH+rsync only.  
# BUILD_ENABLED=false (or BUILD_HOST blank) = identical behavior to before:  
# no SSH is ever attempted. install.sh flips BUILD_ENABLED after a smoke test.  
# ---------------------------------------------------------------------------  
def _env_bool(name: str, default: bool = False) -> bool:  
    raw = os.environ.get(name)  
    if raw is None:  
        return default  
    return raw.strip().lower() in ("1", "true", "yes", "on")  
  
  
BUILD_ENABLED = _env_bool("BUILD_ENABLED", False)  
BUILD_HOST = os.environ.get("BUILD_HOST", "").strip()  
BUILD_USER = os.environ.get("BUILD_USER", "dizerbuild")  
BUILD_KEY_PATH = os.path.expanduser(  
    os.environ.get("BUILD_KEY_PATH", "~/.ssh/dizerbuild_ed25519"))  
BUILD_ROOT = os.environ.get("BUILD_ROOT", "/mnt/build").rstrip("/") or "/mnt/build"  
  
# Repair loop — total attempts = BUILD_MAX_RETRIES + 1. Attempt n>=2 escalates  
# coder tier light -> normal -> heavy.  
BUILD_MAX_RETRIES = int(os.environ.get("BUILD_MAX_RETRIES", "2"))  
BUILD_TIMEOUT_S = int(os.environ.get("BUILD_TIMEOUT_S", "600"))        # file mode  
BUILD_TIMEOUT_TREE = int(os.environ.get("BUILD_TIMEOUT_TREE", "7200"))  # tree mode  
  
# Sandbox resource caps applied via bwrap + prlimit on tadashi.  
BUILD_JOBS = int(os.environ.get("BUILD_JOBS", "4"))  
BUILD_MEM_MB = int(os.environ.get("BUILD_MEM_MB", "3072"))  
BUILD_CPU_S = int(os.environ.get("BUILD_CPU_S", "3600"))  
  
# Tree-mode gate — comma-separated clone-URL allowlist. /run rejects any  
# build_repo not listed here (HTTP 400).  
ALLOWED_REPOS = _slugs("ALLOWED_REPOS", "")  
  
  
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
        cfg = Config(  
            gemini_key=os.environ.get("GEMINI_API_KEY", ""),  
            openai_key=os.environ.get("OPENAI_API_KEY", ""),  
            groq_key=os.environ.get("GROQ_API_KEY", ""),  
            judge_key=os.environ.get("OPENROUTER_API_KEY_JUDGE", ""),  
        )  
        missing = [k for k, v in (  
            ("GEMINI_API_KEY", cfg.gemini_key),  
            ("OPENAI_API_KEY", cfg.openai_key),  
            ("GROQ_API_KEY", cfg.groq_key),  
            ("OPENROUTER_API_KEY_JUDGE", cfg.judge_key),  
        ) if not v]  
        if missing:  
            logger.warning(  
                "API keys not set (provider disabled): %s", ", ".join(missing))  
        if not (cfg.gemini_key or cfg.openai_key or cfg.groq_key):  
            raise RuntimeError(  
                "No coder API keys configured — set at least one of "  
                "OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY")  
        return cfg
