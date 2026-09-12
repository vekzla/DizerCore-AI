# providers.py  
# DizercoreAI — provider integrations (OpenRouter, Groq, Gemini).  
# Each provider exposes a tier-aware call that rotates through a list of model  
# slugs (light / normal / heavy). A safetywall re-checks each output and retries  
# on junk, rotating to the next slug in the tier. A shared RATE_LIMIT_DELAY is  
# awaited before every outbound call so free-tier burst limits aren't tripped.  
import asyncio  
import logging  
  
import httpx  
from google import genai  
from google.genai import types  
  
from config import (  
    config,  
    RATE_LIMIT_DELAY,  
    MAX_SAFETYWALL_TRIES,  
    OPENROUTER_MODELS_BY_TIER,  
    GROQ_MODELS_BY_TIER,  
    GEMINI_MODELS_BY_TIER,  
)  
  
logger = logging.getLogger("DizerCore")  
  
# Shared async HTTP client for the OpenAI-compatible endpoints (OpenRouter, Groq).  
http_client = httpx.AsyncClient(timeout=httpx.Timeout(180.0))  
  
# Gemini uses its own SDK client, configured from the key loaded in config.py.  
gemini_client = genai.Client(api_key=config.gemini_key)  
  
  
# ---------------------------------------------------------------------------  
# Tier selection (user-set complexity 1-5 -> light / normal / heavy)  
# ---------------------------------------------------------------------------  
def tier_for(complexity: int) -> str:  
    """Map the user's 1-5 complexity to a model tier.  
    1-2 = light, 3 = normal, 4-5 = heavy."""  
    try:  
        c = int(complexity)  
    except (TypeError, ValueError):  
        c = 3  
    if c <= 2:  
        return "light"  
    if c == 3:  
        return "normal"  
    return "heavy"  
  
  
def models_for(table: dict, tier: str) -> list:  
    """Return the slug list for a tier, falling back to 'normal' then any list."""  
    if table.get(tier):  
        return table[tier]  
    if table.get("normal"):  
        return table["normal"]  
    # last resort: first non-empty list in the table  
    for v in table.values():  
        if v:  
            return v  
    return []  
  
  
# ---------------------------------------------------------------------------  
# Junk / deflection detection  
# ---------------------------------------------------------------------------  
def is_unusable(text: str) -> bool:  
    """True if a stage produced nothing, or deflected instead of doing the work."""  
    if not text or not text.strip():  
        return True  
    low = text.lower()  
    if len(low.strip()) < 40:            # too short to be real code  
        return True  
    deflections = (  
        "paste the code", "please provide", "could you please",  
        "share the code", "provide the code", "no code provided",  
        "no code was provided", "i don't see any code", "once i have the",  
        "as an ai", "i cannot assist", "i can't assist", "user safety: safe",  
    )  
    return any(d in low for d in deflections)  
  
  
def verdict_pass(text: str) -> bool:  
    """PASS only if the check text does not carry a FAIL verdict."""  
    up = (text or "").upper()  
    if "FAIL" in up:  
        return False  
    return "PASS" in up  
  
  
# ---------------------------------------------------------------------------  
# Low-level single-model calls (throttled)  
# ---------------------------------------------------------------------------  
async def _openrouter_once(prompt: str, model: str, max_tokens: int = 8000) -> str:  
    await asyncio.sleep(RATE_LIMIT_DELAY)           # space out calls  
    r = await http_client.post(  
        "https://openrouter.ai/api/v1/chat/completions",  
        headers={  
            "Authorization": f"Bearer {config.openrouter_key}",  
            "HTTP-Referer": "http://192.168.1.6:8000",  
            "X-Title": "DizercoreAI",  
        },  
        json={  
            "model": model,  
            "messages": [{"role": "user", "content": prompt}],  
            "max_tokens": max_tokens,  
        },  
    )  
    # Fail fast on billing/auth errors so they surface clearly, not as a timeout.  
    if r.status_code in (401, 402, 403):  
        raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:300]}")  
    r.raise_for_status()  
    data = r.json()  
    return (data["choices"][0]["message"].get("content") or "")  
  
  
async def _groq_once(prompt: str, model: str, max_tokens: int = 8000) -> str:  
    await asyncio.sleep(RATE_LIMIT_DELAY)  
    r = await http_client.post(  
        "https://api.groq.com/openai/v1/chat/completions",  
        headers={  
            "Authorization": f"Bearer {config.groq_key}",  
            "Content-Type": "application/json",  
        },  
        json={  
            "model": model,  
            "messages": [{"role": "user", "content": prompt}],  
            "max_tokens": max_tokens,  
        },  
    )  
    if r.status_code in (401, 402, 403, 429):  
        raise RuntimeError(f"Groq {r.status_code}: {r.text[:300]}")  
    r.raise_for_status()  
    data = r.json()  
    return (data["choices"][0]["message"].get("content") or "")  
  
  
async def _gemini_once(prompt: str, model: str, max_tokens: int = 8000) -> str:  
    await asyncio.sleep(RATE_LIMIT_DELAY)  
    resp = await asyncio.to_thread(  
        gemini_client.models.generate_content,  
        model=model,  
        contents=prompt,  
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),  
    )  
    return resp.text or ""  
  
  
# ---------------------------------------------------------------------------  
# Safetywall: rotate through a tier's models until one returns usable output  
# ---------------------------------------------------------------------------  
async def _rotate(call_once, prompt: str, models: list, label: str,  
                  max_tokens: int) -> tuple:  
    """Try each slug in `models` in order until one returns usable output.  
    Returns (text, model_used). Rotation is capped so a broken tier can't  
    loop forever. On total failure returns the last output (even if junk)."""  
    if not models:  
        raise RuntimeError(f"{label}: no models configured for this tier.")  
  
    attempts = max(len(models), MAX_SAFETYWALL_TRIES)  
    last = ""  
    used = models[0]  
    for i in range(attempts):  
        model = models[i % len(models)]  
        used = model  
        try:  
            out = await call_once(prompt, model, max_tokens)  
        except Exception as e:                      # noqa: BLE001  
            logger.warning("%s model %s failed (%s); rotating.", label, model, e)  
            continue  
        if not is_unusable(out):  
            logger.info("%s ok via %s (attempt %d).", label, model, i + 1)  
            return out, model  
        logger.info("%s junk from %s (attempt %d); rotating.", label, model, i + 1)  
        last = out  
    logger.warning("%s exhausted rotation; returning last output.", label)  
    return last, used  
  
  
async def openrouter_generate(prompt: str, tier: str,  
                              max_tokens: int = 8000) -> tuple:  
    models = models_for(OPENROUTER_MODELS_BY_TIER, tier)  
    return await _rotate(_openrouter_once, prompt, models,  
                         f"OpenRouter[{tier}]", max_tokens)  
  
  
async def groq_generate(prompt: str, tier: str,  
                        max_tokens: int = 8000) -> tuple:  
    models = models_for(GROQ_MODELS_BY_TIER, tier)  
    return await _rotate(_groq_once, prompt, models,  
                         f"Groq[{tier}]", max_tokens)  
  
  
async def gemini_generate(prompt: str, tier: str,  
                          max_tokens: int = 8000) -> tuple:  
    models = models_for(GEMINI_MODELS_BY_TIER, tier)  
    return await _rotate(_gemini_once, prompt, models,  
                         f"Gemini[{tier}]", max_tokens)  
  
  
# ---------------------------------------------------------------------------  
# Confidence: a tiny scored self-check (0-100) — returns "" on any failure.  
# ---------------------------------------------------------------------------  
async def confidence(call_once, model: str, request: str, code: str) -> str:  
    """Ask a model to rate 0-100 how well `code` satisfies `request`.  
    Uses a tiny max_tokens and swallows all errors so it never fails a job."""  
    try:  
        out = await call_once(  
            "Rate from 0 to 100 how well the CODE satisfies the REQUEST. "  
            "Reply with ONLY the integer.\n\nREQUEST:\n" + request +  
            "\n\nCODE:\n" + code,  
            model, 8)  
        digits = "".join(ch for ch in out if ch.isdigit())[:3]  
        return digits if digits else ""  
    except Exception:                                # noqa: BLE001  
        return ""