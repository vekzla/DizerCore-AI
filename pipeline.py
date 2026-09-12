# pipeline.py  
# DizercoreAI — the 3-stage pipeline runner.  
# Stage 1 OpenRouter (generate) -> Stage 2 Groq (verify) -> Stage 3 Gemini (final clean).  
# The user-set complexity (1-5) picks ONE tier for the whole job:  
#   1-2 = light, 3 = normal, 4-5 = heavy.  
# Confidence is judged ONLY by Inkling AFTER all stages run: it reads each  
# stage's output against the user's original request, scores it 0-100, and the  
# highest-scoring stage becomes the "best" summary. The generator AIs never  
# self-score.  
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
            else:  
                final = "[Gemini skipped — showing Groq's verified output]\n\n" + verify  
                job.steps["final_model"] = "(skipped)"  
            job.steps["final"] = final  
            job.touch(); save_job(job)  
  
            # ---- Inkling judge: sole scorer of every stage. ----  
            if job.stages.get("inkling", True):  
                logger.info("[Job %s] Inkling judging each stage...", job.id)  
                candidates = [  
                    ("OpenRouter", "generate", code, job.stages.get("openrouter", True)),  
                    ("Groq",       "verify",   verify, job.stages.get("groq", True)),  
                    ("Gemini",     "final",    final, job.stages.get("gemini", True)),  
                ]  
                scores = []  
                for name, key, output, ran in candidates:  
                    if not ran:  
                        job.steps[key + "_conf"] = ""  
                        continue  
                    try:  
                        pct = await inkling_confidence(job.prompt, output)  
                    except Exception as e:  # noqa: BLE001  
                        logger.info("[Job %s] %s scoring skipped (%s).",  
                                    job.id, name, e)  
                        pct = ""  
                    job.steps[key + "_conf"] = pct  
                    job.touch(); save_job(job)  
                    try:  
                        scores.append((int(pct), name, key))  
                    except (TypeError, ValueError):  
                        pass  
                if scores:  
                    # Highest % wins. Reuse that stored score for the summary.  
                    scores.sort(reverse=True)  
                    best_pct, best_name, _best_key = scores[0]  
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
