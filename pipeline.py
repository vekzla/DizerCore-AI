# pipeline.py  
# DizercoreAI — the 3-stage pipeline runner.  
# Stage 1 OpenRouter (generate) -> Stage 2 Groq (verify) -> Stage 3 Gemini (final clean).  
# The user-set complexity (1-5) picks ONE tier for the whole job:  
#   1-2 = light, 3 = normal, 4-5 = heavy.  
# Each stage: skip marker if unticked, safetywall retry on junk, per-stage  
# model-used + confidence recorded into job.steps.  
import asyncio  
import logging  
  
from db import State, Job, save_job, TASKS  
from providers import (  
    openrouter_generate,  
    groq_generate,  
    gemini_generate,  
    confidence,  
)  
  
logger = logging.getLogger("DizerCore")  
  
MAX_CONCURRENT_JOBS = 2  
job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)  
  
  
def tier_for(complexity: int) -> str:  
    """Map the user's 1-5 complexity onto a model tier.  
    1-2 = light, 3 = normal, 4-5 = heavy. Anything odd defaults to normal."""  
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
    """Per-stage confidence: ask the scorer how well `output` meets `request`.  
    Wrapped so a scorer 429/paywall just leaves the % blank — never fails the job."""  
    try:  
        pct = await confidence(request, output)  
    except Exception as e:  # noqa: BLE001  
        logger.info("Job %s: %s confidence skipped (%s).", job.id, stage_label, e)  
        pct = ""  
    job.steps.setdefault("confidence", {})[stage_label] = pct  
  
  
async def run_pipeline(job: Job) -> None:  
    try:  
        async with job_semaphore:  
            job.state = State.RUNNING  
            job.touch(); save_job(job)  
  
            tier = tier_for(getattr(job, "complexity", 3))  
            logger.info("[Job %s] complexity=%s -> tier=%s",  
                        job.id, getattr(job, "complexity", 3), tier)  
  
            # ---- Stage 1: OpenRouter reads raw input and CREATES the code. ----  
            code = job.prompt                      # if OpenRouter is off, forward raw input  
            if job.stages.get("openrouter", True):  
                logger.info("[Job %s] STAGE 1/3 OpenRouter generating (tier=%s)...",  
                            job.id, tier)  
                gen_prompt = (  
                    "Write complete, runnable code implementing this request. "  
                    "Return ONLY code, minimal comments. Do NOT ask for the code — "  
                    "you must produce it yourself.\n\nREQUEST:\n" + job.prompt)  
                code, model_used = await openrouter_generate(gen_prompt, tier=tier)  
                job.steps["model"] = {"generate": model_used}  
                await _score("generate", job.prompt, code, job)  
            else:  
                code = "[OpenRouter skipped — using your raw input]\n\n" + job.prompt  
                job.steps.setdefault("model", {})["generate"] = "(skipped)"  
            job.steps["generate"] = code  
            job.touch(); save_job(job)  
  
            # ---- Stage 2: Groq VERIFIES the code against the original input. ----  
            verify = code                          # if Groq is off, forward stage-1 code  
            if job.stages.get("groq", True):  
                logger.info("[Job %s] STAGE 2/3 Groq verifying (tier=%s)...",  
                            job.id, tier)  
                verify_prompt = (  
                    "Verify this code against the original request. Fix any issues, "  
                    "then return the improved code and a short note of what you changed. "  
                    "Do NOT ask for the code — it is provided below.\n\n"  
                    "REQUEST:\n" + job.prompt + "\n\nCODE:\n" + code)  
                verify, model_used = await groq_generate(verify_prompt, tier=tier)  
                job.steps.setdefault("model", {})["verify"] = model_used  
                await _score("verify", job.prompt, verify, job)  
            else:  
                verify = "[Groq skipped — forwarding OpenRouter's code]\n\n" + code  
                job.steps.setdefault("model", {})["verify"] = "(skipped)"  
            job.steps["verify"] = verify  
            job.touch(); save_job(job)  
  
            # ---- Stage 3: Gemini VERIFIES vs input, returns final cleaned code. ----  
            final = verify                         # if Gemini is off, last output is final  
            if job.stages.get("gemini", True):  
                logger.info("[Job %s] STAGE 3/3 Gemini final cleanup (tier=%s)...",  
                            job.id, tier)  
                final_prompt = (  
                    "Verify this code satisfies the original request, then return the "  
                    "FINAL cleaned, optimised and refactored code. Return the complete "  
                    "code, not a verdict.\n\n"  
                    "REQUEST:\n" + job.prompt + "\n\nCODE:\n" + verify)  
                final, model_used = await gemini_generate(final_prompt, tier=tier)  
                job.steps.setdefault("model", {})["final"] = model_used  
                await _score("final", job.prompt, final, job)  
            else:  
                final = "[Gemini skipped — showing Groq's verified output]\n\n" + verify  
                job.steps.setdefault("model", {})["final"] = "(skipped)"  
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
        TASKS.pop(job.id, None)