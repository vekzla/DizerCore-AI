# pipeline.py  
# DizercoreAI — the 3-stage pipeline runner.  
# Stage 1 OpenRouter (generate) -> Stage 2 Groq (verify) -> Stage 3 Gemini (final clean).  
# The user-set complexity (1-5) picks ONE tier for the whole job:  
#   1-2 = light, 3 = normal, 4-5 = heavy.  
# Confidence: a SINGLE judge (Inkling) scores each stage's output against the  
# user's original request. The generators never self-score. After all stages,  
# the stage with the HIGHEST % is declared the winner in the summary box.  
import asyncio  
import logging  
  
import runtime  
from db import State, Job, save_job  
from providers import (  
    openrouter_generate,  
    groq_generate,  
    gemini_generate,  
    judge_confidence,  
)  
  
logger = logging.getLogger("DizerCore")  
  
# Maps internal step labels -> the friendly provider name shown in the summary.  
_STAGE_NAMES = {  
    "generate": "OpenRouter",  
    "verify": "Groq",  
    "final": "Gemini",  
}  
  
  
def tier_for(complexity: int) -> str:  
    try:  
        c = int(complexity)  
    except (TypeError, ValueError):  
        return "normal"  
    if c <= 2:  
        return "light"  
    if c >= 4:  
        return "heavy"  
    return "normal"  
  
  
async def _score(stage_label: str, request: str, output: str, job: Job) -> None:  
    """Inkling scores this stage against the user's request. Only runs when the  
    Inkling judge is enabled for the job; any scorer error leaves the % blank."""  
    if not job.stages.get("inkling", True):  
        return  
    try:  
        pct = await judge_confidence(request, output)  
    except Exception as e:  # noqa: BLE001  
        logger.info("Job %s: %s confidence skipped (%s).", job.id, stage_label, e)  
        pct = ""  
    job.steps[stage_label + "_conf"] = pct  
  
  
def _pick_winner(job: Job) -> None:  
    """Winner = the stage with the highest Inkling %. Reuses the already-computed  
    per-stage scores (no extra model call) and writes the summary box text."""  
    if not job.stages.get("inkling", True):  
        job.steps["summary"] = ""  
        return  
    scored = []  
    for label, name in _STAGE_NAMES.items():  
        raw = job.steps.get(label + "_conf", "")  
        try:  
            val = int(raw)  
        except (TypeError, ValueError):  
            continue  
        scored.append((val, name))  
    if not scored:  
        job.steps["summary"] = "Inkling could not score any stage."  
        return  
    scored.sort(reverse=True)               # highest % first  
    val, name = scored[0]  
    job.steps["summary"] = (  
        f"Best output: {name} — {val}% confidence "  
        f"(highest of the {len(scored)} stage(s) scored by Inkling)."  
    )  
  
  
async def run_pipeline(job: Job) -> None:  
    try:  
        async with runtime.job_semaphore:  
            job.state = State.RUNNING  
            job.touch(); save_job(job)  
  
            tier = tier_for(getattr(job, "complexity", 3))  
            logger.info("[Job %s] complexity=%s -> tier=%s",  
                        job.id, getattr(job, "complexity", 3), tier)  
  
            # ---- Stage 1: OpenRouter creates the code. ----  
            code = job.prompt  
            if job.stages.get("openrouter", True):  
                logger.info("[Job %s] STAGE 1/3 OpenRouter generating (tier=%s)...",  
                            job.id, tier)  
                gen_prompt = (  
                    "Write complete, runnable code implementing this request. "  
                    "Return ONLY code, minimal comments. Do NOT ask for the code — "  
                    "you must produce it yourself.\n\nREQUEST:\n" + job.prompt)  
                code, model_used = await openrouter_generate(gen_prompt, tier=tier)  
                job.steps["generate_model"] = model_used  
                await _score("generate", job.prompt, code, job)  
            else:  
                code = "[OpenRouter skipped — using your raw input]\n\n" + job.prompt  
                job.steps["generate_model"] = "(skipped)"  
            job.steps["generate"] = code  
            job.touch(); save_job(job)  
  
            # ---- Stage 2: Groq verifies the code. ----  
            verify = code  
            if job.stages.get("groq", True):  
                logger.info("[Job %s] STAGE 2/3 Groq verifying (tier=%s)...",  
                            job.id, tier)  
                verify_prompt = (  
                    "Verify this code against the original request. Fix any issues, "  
                    "then return the improved code and a short note of what you changed. "  
                    "Do NOT ask for the code — it is provided below.\n\n"  
                    "REQUEST:\n" + job.prompt + "\n\nCODE:\n" + code)  
                verify, model_used = await groq_generate(verify_prompt, tier=tier)  
                job.steps["verify_model"] = model_used  
                await _score("verify", job.prompt, verify, job)  
            else:  
                verify = "[Groq skipped — forwarding OpenRouter's code]\n\n" + code  
                job.steps["verify_model"] = "(skipped)"  
            job.steps["verify"] = verify  
            job.touch(); save_job(job)  
  
            # ---- Stage 3: Gemini returns final cleaned code. ----  
            final = verify  
            if job.stages.get("gemini", True):  
                logger.info("[Job %s] STAGE 3/3 Gemini final cleanup (tier=%s)...",  
                            job.id, tier)  
                final_prompt = (  
                    "Verify this code satisfies the original request, then return the "  
                    "FINAL cleaned, optimised and refactored code. Return the complete "  
                    "code, not a verdict.\n\n"  
                    "REQUEST:\n" + job.prompt + "\n\nCODE:\n" + verify)  
                final, model_used = await gemini_generate(final_prompt, tier=tier)  
                job.steps["final_model"] = model_used  
                await _score("final", job.prompt, final, job)  
            else:  
                final = "[Gemini skipped — showing Groq's verified output]\n\n" + verify  
                job.steps["final_model"] = "(skipped)"  
            job.steps["final"] = final  
            job.touch(); save_job(job)  
  
            # ---- Inkling summary: whichever stage scored highest wins. ----  
            _pick_winner(job)  
  
            job.state = State.DONE  
            job.touch(); save_job(job)  
            logger.info("[Job %s] done.", job.id)  
    except asyncio.CancelledError:  
        job.state = State.CANCELLED  
        job.error = "Cancelled by user."  
        job.touch(); save_job(job)  
        logger.info("[Job %s] cancelled.", job.id)  
        raise  
    except Exception as e:  # noqa: BLE001  
        job.state = State.FAILED  
        job.error = str(e)  
        job.touch(); save_job(job)  
        logger.exception("[Job %s] failed: %s", job.id, e)  
    finally:  
        runtime.TASKS.pop(job.id, None)
