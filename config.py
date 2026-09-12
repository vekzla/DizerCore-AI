# config.py  
# DizercoreAI — configuration, constants, model tiers, and shared predicates.  
import logging  
import os  
from dataclasses import dataclass  
from logging.handlers import RotatingFileHandler  
  
# --------------------------------------------------------------------------- #  
# Paths (all persistent data lives on the SSD, set via DIZER_DATA_DIR)  
# --------------------------------------------------------------------------- #  
DATA_DIR = os.environ.get("DIZER_DATA_DIR", "/mnt/dizerdata/dizercore")  
os.makedirs(DATA_DIR, exist_ok=True)  
USERS_DB = os.path.join(DATA_DIR, "dizer_users.db")  
JOBS_DB = os.path.join(DATA_DIR, "dizer_jobs.db")  
SESSIONS_DB = os.path.join(DATA_DIR, "dizer_sessions.db")  
LOG_FILE = os.path.join(DATA_DIR, "dizercore.log")  
  
# --------------------------------------------------------------------------- #  
# Logging (console + rotating file; guarded so re-import never stacks handlers)  
# --------------------------------------------------------------------------- #  
logger = logging.getLogger("DizerCore")  
logger.setLevel(logging.INFO)  
if not logger.handlers:  
    _fmt = logging.Formatter("%(asctime)s %(levelname)s [DizerCore] %(message)s")  
    _sh = logging.StreamHandler()  
    _sh.setFormatter(_fmt)  
    logger.addHandler(_sh)  
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)  
    _fh.setFormatter(_fmt)  
    logger.addHandler(_fh)  
  
# --------------------------------------------------------------------------- #  
# Limits  
# --------------------------------------------------------------------------- #  
MAX_PROMPT_CHARS = 200_000  
MAX_FILE_BYTES = 5_000_000  
MAX_TOTAL_FILE_BYTES = 20_000_000  
MAX_CONCURRENT_JOBS = 2  
MAX_PIPELINE_RETRIES = 2        # times a stage re-interrogates itself on junk  
MAX_SAFETYWALL_TRIES = 3        # cap for junk-retry loops  
  
# Seconds inserted before EVERY outbound model call so bursts of requests do  
# not trip the free-tier per-minute limits. Override via the env var.  
RATE_LIMIT_DELAY = float(os.environ.get("RATE_LIMIT_DELAY", "6"))  
  
# --------------------------------------------------------------------------- #  
# Complexity tiers  
#   The USER picks a complexity 1-5 in the dashboard (NOT an auto-classifier).  
#   1-2 -> light, 3 -> normal, 4-5 -> heavy. If a level-3 run gives poor  
#   output, bump to 4 next time. Each tier maps to a LIST of slugs that the  
#   safetywall rotates through (first that returns usable output wins).  
# --------------------------------------------------------------------------- #  
def tier_for(level) -> str:  
    """Map a 1-5 user complexity level to a tier name."""  
    try:  
        n = int(level)  
    except (TypeError, ValueError):  
        n = 3  
    n = max(1, min(5, n))  
    if n <= 2:  
        return "light"  
    if n == 3:  
        return "normal"  
    return "heavy"  
  
  
def _tier_map(var: str, light: list, normal: list, heavy: list) -> dict:  
    """Per-provider tier map of slug LISTS. Each tier is overridable via a  
    comma-separated {VAR}_{TIER} env var (e.g. OPENROUTER_MODEL_HEAVY=a,b)."""  
    def _slugs(tier_name: str, default: list) -> list:  
        raw = os.environ.get(f"{var}_{tier_name}")  
        if raw:  
            return [s.strip() for s in raw.split(",") if s.strip()]  
        return default  
    return {  
        "light": _slugs("LIGHT", light),  
        "normal": _slugs("NORMAL", normal),  
        "heavy": _slugs("HEAVY", heavy),  
    }  
  
  
# NOTE: verify each slug is live on the provider's models page. A wrong/retired  
# slug just errors and the safetywall rotates to the next one in the list.  
OPENROUTER_MODELS_BY_TIER = _tier_map(  
    "OPENROUTER_MODEL",  
    light=["google/gemma-4-31b-it:free"],  
    normal=["poolside/laguna-s-2.1:free"],  
    heavy=["nex-agi/nex-n2.5-pro:free"],  
)  
GROQ_MODELS_BY_TIER = _tier_map(  
    "GROQ_MODEL",  
    light=["openai/gpt-oss-20b"],  
    normal=["openai/gpt-oss-120b"],  
    heavy=["openai/gpt-oss-120b"],  
)  
GEMINI_MODELS_BY_TIER = _tier_map(  
    "GEMINI_MODEL",  
    light=["gemini-3.5-flash-lite"],  
    normal=["gemini-3.6-flash"],  
    heavy=["gemini-3.6-flash"],  
)  
  
# --------------------------------------------------------------------------- #  
# Deflection / verdict detection  
# --------------------------------------------------------------------------- #  
def _is_unusable(text: str) -> bool:  
    """True if a stage produced nothing, or deflected instead of doing the work."""  
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
  
  
def _verdict_pass(text: str) -> bool:  
    up = (text or "").upper()  
    if "FAIL" in up:  
        return False  
    return "PASS" in up  
  
  
# --------------------------------------------------------------------------- #  
# API keys  
# --------------------------------------------------------------------------- #  
@dataclass  
class Config:  
    gemini_key: str  
    openrouter_key: str  
    groq_key: str  
  
    @staticmethod  
    def from_env() -> "Config":  
        missing = [k for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY")  
                   if not os.environ.get(k)]  
        if missing:  
            raise RuntimeError(  
                f"Missing required environment variables: {', '.join(missing)}")  
        return Config(  
            gemini_key=os.environ["GEMINI_API_KEY"],  
            openrouter_key=os.environ["OPENROUTER_API_KEY"],  
            groq_key=os.environ["GROQ_API_KEY"],  
        )
