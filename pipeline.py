# pipeline.py  
# DizercoreAI — the 3-stage pipeline runner.  
# Stage 1 OpenRouter (generate) -> Stage 2 Groq (verify) -> Stage 3 Gemini (final clean).  
# The user-set complexity (1-5) picks ONE tier for the whole job:  
#   1-2 = light, 3 = normal, 4-5 = heavy.  
# Each stage's confidence is scored by its OWN provider (see providers.py) so  
# one provider being rate-limited never blanks every score.  
import asyncio  
import logging  
  
import runtime  
from db import State, Job, save_job  
from providers import (  
    openrouter_generate,  
    groq_generate,  
    gemini_generate,  
    openrouter_confidence,  
    groq_confidence,  
    gemini_confidence,  
)  
  
logger = logging.getLogger("DizerCore")  
  
  
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
  
  
async def _score(stage_label: str, scorer, request: str, output: str, job: Job) -> None:  
    """Per-stage confidence via the stage's own provider; a scorer error just  
    leaves the % blank so it never fails the job."""  
    try:  
        pct = await scorer(request, output)  
    except Exception as e:  # noqa: BLE001  
        logger.info("Job %s: %s confidence skipped (%s).", job.id, stage_label, e)  
        pct = ""  
    job.steps[stage_label + "_conf"] = pct  
  
  
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
                await _score("generate", openrouter_confidence, job.prompt, code, job)  
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
                await _score("verify", groq_confidence, job.prompt, verify, job)  
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
                await _score("final", gemini_confidence, job.prompt, final, job)  
            else:  
                final = "[Gemini skipped — showing Groq's verified output]\n\n" + verify  
                job.steps["final_model"] = "(skipped)"  
            job.steps["final"] = final  
            job.touch(); save_job(job)  
  
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
