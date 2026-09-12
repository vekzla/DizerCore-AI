# pipeline.py  
# DizercoreAI — the 3-stage pipeline runner.  
# Stage 1 OpenRouter (generate) -> Stage 2 Groq (verify) -> Stage 3 Gemini (final clean).  
# The user-set complexity (1-5) picks ONE tier for the whole job:  
#   1-2 = light, 3 = normal, 4-5 = heavy.  
# Confidence is scored ONLY by the Inkling judge (thinkingmachines/inkling-small  
# via OpenRouter, reasoning enabled). The three generator AIs never self-score  
# and never post anything to Inkling — Inkling only reads the user's original  
# request and each stage's output. The stage with the highest % is the winner,  
# summarised in its own box. All Inkling work is gated on the `inkling` stage.  
import asyncio  
import logging  
  
import runtime  
from db import State, Job, save_job  
from providers import (  
    openrouter_generate,  
    groq_generate,  
    gemini_generate,  
    inkling_confidence,  
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
  
  
def _to_int(pct: str) -> int:  
    """Parse a confidence string like '87' to an int; junk -> -1 so it never wins."""  
    try:  
        return int(str(pct).strip())  
    except (TypeError, ValueError):  
        return -1  
  
  
async def _judge(stage_label: str, request: str, output: str, job: Job) -> None:  
    """Score one stage's output with the Inkling judge — the SOLE scorer.  
    Inkling reads only the user's original `request` and the stage `output`;  
    the generator AIs do not post to it. A judge error just leaves the %  
    blank so it never fails the job."""  
    try:  
        pct = await inkling_confidence(request, output)  
    except Exception as e:  # noqa: BLE001  
        logger.info("Job %s: %s judge skipped (%s).", job.id, stage_label, e)  
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
  
            # ---- Stage 1: OpenRouter creates the code (no self-score). ----  
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
            else:  
                code = "[OpenRouter skipped — using your raw input]\n\n" + job.prompt  
                job.steps["generate_model"] = "(skipped)"  
            job.steps["generate"] = code  
            job.touch(); save_job(job)  
  
            # ---- Stage 2: Groq verifies the code (no self-score). ----  
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
            else:  
                verify = "[Groq skipped — forwarding OpenRouter's code]\n\n" + code  
                job.steps["verify_model"] = "(skipped)"  
            job.steps["verify"] = verify  
            job.touch(); save_job(job)  
  
            # ---- Stage 3: Gemini returns final cleaned code (no self-score). ----  
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
            else:  
                final = "[Gemini skipped — showing Groq's verified output]\n\n" + verify  
                job.steps["final_model"] = "(skipped)"  
            job.steps["final"] = final  
            job.touch(); save_job(job)  
  
            # ---- Inkling judge: the SOLE scorer. Reads each enabled stage's  
            #      output against the user's original prompt, then names the  
            #      highest-scoring stage as the winner in its own summary box. ----  
            if job.stages.get("inkling", True):  
                logger.info("[Job %s] Inkling judging all stages...", job.id)  
                # label -> (display name, stage toggle key, output text)  
                candidates = [  
                    ("generate", "OpenRouter", "openrouter", code),  
                    ("verify",   "Groq",       "groq",       verify),  
                    ("final",    "Gemini",     "gemini",     final),  
                ]  
                best_name, best_pct = "", -1  
                for label, name, toggle, output in candidates:  
                    if not job.stages.get(toggle, True):  
                        continue  
                    await _judge(label, job.prompt, output, job)  
                    pct = _to_int(job.steps.get(label + "_conf", ""))  
                    if pct > best_pct:  
                        best_name, best_pct = name, pct  
  
                if best_pct >= 0:  
                    job.steps["summary"] = (  
                        f"Best is {best_name} because it scored highest against "  
                        f"your request ({best_pct}%).")  
                    job.steps["summary_conf"] = str(best_pct)  
                else:  
                    job.steps["summary"] = "Inkling could not score any stage."  
                    job.steps["summary_conf"] = ""  
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
