# providers.py  
# DizercoreAI — provider integrations (OpenRouter, Groq, Gemini).  
# Tier-aware calls rotate model slugs (light/normal/heavy). A safetywall  
# re-checks each output and retries on junk, rotating to the next slug.  
# RATE_LIMIT_DELAY is awaited before every outbound call to avoid burst caps.  
# Shared clients/keys are read from runtime.* (set at startup) — NOT imported  
# from config as an instance, which avoids the import-time ImportError.  
import asyncio  
import logging  
  
from google.genai import types  
  
import runtime  
from config import (  
    RATE_LIMIT_DELAY,  
    MAX_SAFETYWALL_TRIES,  
    OPENROUTER_MODELS_BY_TIER,  
    GROQ_MODELS_BY_TIER,  
    GEMINI_MODELS_BY_TIER,  
)  
  
logger = logging.getLogger("dizercore")  
  
  
# ---------------------------------------------------------------------------  
# Tier + junk helpers  
# ---------------------------------------------------------------------------  
def tier_for(complexity: int) -> str:  
    """1-2 = light, 3 = normal, 4-5 = heavy (user-set on each job)."""  
    try:  
        c = int(complexity)  
    except (TypeError, ValueError):  
        c = 3  
    if c <= 2:  
        return "light"  
    if c == 3:  
        return "normal"  
    return "heavy"  
  
  
def is_unusable(text: str) -> bool:  
    """True if a stage produced nothing, or deflected instead of doing the work."""  
    if not text or not text.strip():  
        return True  
    low = text.lower()  
    deflections = (  
        "paste the code", "please provide", "could you please",  
        "share the code", "provide the code", "no code provided",  
        "no code was provided", "i don't see any code", "once i have the",  
    )  
    return any(d in low for d in deflections)  
  
  
# ---------------------------------------------------------------------------  
# Low-level single-slug calls (each returns text for one model slug)  
# ---------------------------------------------------------------------------  
async def _openrouter_once(prompt: str, model: str, max_tokens: int) -> str:  
    await asyncio.sleep(RATE_LIMIT_DELAY)  
    r = await runtime.http_client.post(  
        "https://openrouter.ai/api/v1/chat/completions",  
        headers={  
            "Authorization": f"Bearer {runtime.cfg.openrouter_key}",  
            "HTTP-Referer": "http://192.168.1.6:8000",  
            "X-Title": "DizerCore.AI",  
        },  
        json={"model": model,  
              "messages": [{"role": "user", "content": prompt}],  
              "max_tokens": max_tokens},  
    )  
    if r.status_code in (401, 402, 403):  
        raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:300]}")  
    r.raise_for_status()  
    return (r.json()["choices"][0]["message"].get("content") or "")  
  
  
async def _groq_once(prompt: str, model: str, max_tokens: int) -> str:  
    await asyncio.sleep(RATE_LIMIT_DELAY)  
    r = await runtime.http_client.post(  
        "https://api.groq.com/openai/v1/chat/completions",  
        headers={  
            "Authorization": f"Bearer {runtime.cfg.groq_key}",  
            "Content-Type": "application/json",  
        },  
        json={"model": model,  
              "messages": [{"role": "user", "content": prompt}],  
              "max_tokens": max_tokens},  
    )  
    if r.status_code in (401, 402, 403, 429):  
        raise RuntimeError(f"Groq {r.status_code}: {r.text[:300]}")  
    r.raise_for_status()  
    return (r.json()["choices"][0]["message"].get("content") or "")  
  
  
async def _gemini_once(prompt: str, model: str, max_tokens: int) -> str:  
    await asyncio.sleep(RATE_LIMIT_DELAY)  
    resp = await asyncio.to_thread(  
        runtime.gemini_client.models.generate_content,  
        model=model,  
        contents=prompt,  
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),  
    )  
    return resp.text or ""  
  
  
# ---------------------------------------------------------------------------  
# Tier-aware rotation with safetywall  
# ---------------------------------------------------------------------------  
async def _rotate(call_once, models: list, prompt: str, max_tokens: int):  
    """Try each slug in the tier; retry on junk. Returns (text, slug_used)."""  
    last = ""  
    used = models[0] if models else ""  
    for slug in models[:MAX_SAFETYWALL_TRIES] or [used]:  
        used = slug  
        try:  
            last = await call_once(prompt, slug, max_tokens)  
        except Exception as e:                       # noqa: BLE001  
            logger.warning("Model %s failed: %s", slug, e)  
            last = ""  
        if not is_unusable(last):  
            return last, slug  
        logger.info("Model %s produced junk; rotating.", slug)  
    return last, used  
  
  
async def openrouter_generate(prompt, tier="normal", max_tokens=1500):  
    return await _rotate(_openrouter_once,  
                         OPENROUTER_MODELS_BY_TIER.get(tier, []),  
                         prompt, max_tokens)  
  
  
async def groq_generate(prompt, tier="normal", max_tokens=1500):  
    return await _rotate(_groq_once,  
                         GROQ_MODELS_BY_TIER.get(tier, []),  
                         prompt, max_tokens)  
  
  
async def gemini_generate(prompt, tier="normal", max_tokens=1500):  
    return await _rotate(_gemini_once,  
                         GEMINI_MODELS_BY_TIER.get(tier, []),  
                         prompt, max_tokens)  
  
  
# ---------------------------------------------------------------------------  
# Per-stage confidence (0-100). Swallows all errors so it never fails a job.  
# ---------------------------------------------------------------------------  
async def confidence(call_once, model: str, request: str, code: str) -> str:  
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
