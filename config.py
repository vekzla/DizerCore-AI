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
  
# Cap for junk-retry rotation loops. Must be >= the length of the longest tier  
# list below, otherwise fallback slugs past this index are never reached.  
# Env-overridable so ops can tune it without a code change.  
MAX_SAFETYWALL_TRIES = int(os.environ.get("MAX_SAFETYWALL_TRIES", "8"))  
  
# Seconds inserted before EVERY outbound model call so bursts of requests do  
# not trip the free-tier per-minute limits. Override via the env var.  
RATE_LIMIT_DELAY = float(os.environ.get("RATE_LIMIT_DELAY", "6"))  
  
# --------------------------------------------------------------------------- #  
# Inkling — kept for backward compatibility only.  
#   Historically the sole confidence judge. Judging is now performed by the  
#   JUDGE_MODELS pool (see below); INKLING_MODEL remains defined so any legacy  
#   env/config references still resolve.  
# --------------------------------------------------------------------------- #  
INKLING_MODEL = os.environ.get("INKLING_MODEL", "thinkingmachines/inkling-small:free")  
  
  
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
# Each tier holds MULTIPLE coding slugs so a failed/junk model rotates to the  
# next fallback within the same tier. Complexity 1-2 -> light, 3 -> normal,  
# 4-5 -> heavy.  
OPENROUTER_MODELS_BY_TIER = _tier_map(  
    "OPENROUTER_MODEL",  
    light=[  
        "liquid/lfm-2.5-2.6b:free",  
        "nvidia/nemotron-3.5-lightning:free",  
        "poolside/laguna-xs-2.1:free",  
        "google/gemma-4-26b-a4b-it:free",  
        "thinkingmachines/inkling-small:free",  
        "nex-agi/nex-n2.5-mini:free",  
        "cohere/north-mini-code:free",  
    ],  
    normal=[  
        "poolside/laguna-s-2.1:free",  
        "google/gemma-4-31b-it:free",  
        "thinkingmachines/inkling:free",  
        "nex-agi/nex-n2.5-pro:free",  
    ],  
    heavy=[  
        "nvidia/nemotron-3-super-120b-a12b:free",  
        "nvidia/nemotron-3-ultra-550b-a55b:free",  
    ],  
)  
GROQ_MODELS_BY_TIER = _tier_map(  
    "GROQ_MODEL",  
    light=[  
        "openai/gpt-oss-20b",  
        "qwen/qwen3.6-27b",  
        "groq/compound-mini",  
    ],  
    normal=[  
        "openai/gpt-oss-120b",  
        "qwen/qwen3.8-27b",  
        "groq/compound",  
    ],  
    heavy=[  
        "openai/gpt-oss-120b",  
        "qwen/qwen3.8-27b",  
        "groq/compound",  
    ],  
)  
GEMINI_MODELS_BY_TIER = _tier_map(  
    "GEMINI_MODEL",  
    # Flash-Lite = 500 RPD / 15 RPM; full Flash = only 20 RPD / 5 RPM.  
    # Lead every tier with Flash-Lite for headroom; full Flash is heavy-only,  
    # and Flash-Lite sits under it as the fallback when the 20/day cap is hit.  
    light=[  
        "gemini-3.5-flash-lite",  
        "gemini-3.1-flash-lite",  
    ],  
    normal=[  
        "gemini-3.5-flash-lite",  
        "gemini-3.1-flash-lite",  
    ],  
    heavy=[  
        "gemini-3.8-flash",  
        "gemini-3.6-flash",  
        "gemini-3.5-flash-lite",  
        "gemini-3.1-flash-lite",  
    ],  
)  
# --------------------------------------------------------------------------- #  
# Judge models — score each agent's output 0-100 AFTER all stages run.  
#   Every model in JUDGE_MODELS scores each candidate; any judge that returns  
#   non-numeric output (or errors) is DISCARDED and replaced by the next unused  
#   slug from JUDGE_FALLBACK_MODELS. The surviving numeric scores are averaged,  
#   and the agent (OpenRouter / Groq / Gemini) with the highest average wins.  
#   Both lists are comma-separated env-overridable.  
# --------------------------------------------------------------------------- #  
def _list_from_env(var: str, default: list) -> list:  
    raw = os.environ.get(var)  
    if raw:  
        return [s.strip() for s in raw.split(",") if s.strip()]  
    return default  
  
  
JUDGE_MODELS = _list_from_env(  
    "JUDGE_MODELS",  
    [  
        "inclusionai/ling-3.0-flash-vl:free",  
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  
        "nvidia/nemotron-3.5-content-safety:free",  
    ],  
)  
JUDGE_FALLBACK_MODELS = _list_from_env("JUDGE_FALLBACK_MODELS", [])  
  
# --------------------------------------------------------------------------- #  
# Reasoning flag — EVERY slug used anywhere (generation tiers + judges +  
# legacy Inkling) is called with "reasoning": {"enabled": True}. Built  
# programmatically so new slugs above are automatically included.  
# --------------------------------------------------------------------------- #  
REASONING_MODELS = set()  
for _tier_list in OPENROUTER_MODELS_BY_TIER.values():  
    REASONING_MODELS.update(_tier_list)  
REASONING_MODELS.update(JUDGE_MODELS)  
REASONING_MODELS.update(JUDGE_FALLBACK_MODELS)  
REASONING_MODELS.add(INKLING_MODEL)  
  
  
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
