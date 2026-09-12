# pipeline.py  
# DizercoreAI — the 3-agent pipeline runner.  
# OpenRouter, Groq, and Gemini each INDEPENDENTLY write their own code for the  
# user's request (no cross-checking, no chaining). All three run in parallel.  
# The user-set complexity (1-5) picks ONE tier for the whole job:  
#   1-2 = light, 3 = normal, 4-5 = heavy.  
# Confidence is judged AFTER all agents finish by the JUDGE_MODELS pool: every  
# judge scores each agent's output 0-100 against the user's original request,  
# non-numeric judges are dropped (and replaced by fallback judges), the  
# surviving scores are averaged, and the highest-AVERAGE agent becomes the  
# "best" summary. The generator AIs never self-score.  
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
  
# Every agent gets the SAME independent instruction + the user's raw request.  
_GEN_PROMPT = (  
    "Write complete, runnable code implementing this request. "  
    "Return ONLY code, minimal comments. Do NOT ask for the code — "  
    "you must produce it yourself.\n\nREQUEST:\n"  
)  
  
  
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
  
  
async def _run_agent(generate, enabled: bool, prompt: str, tier: str,  
                     skip_msg: str):  
    """Run ONE agent independently. Returns (output, model_used).  
    If the agent is toggled off, returns a skip marker instead of calling out."""  
    if not enabled:  
        return skip_msg, "(skipped)"  
    try:  
        return await generate(prompt, tier=tier)  
    except Exception as e:  # noqa: BLE001  
        logger.warning("Agent generation failed: %s", e)  
        return "", ""  
  
  
async def run_pipeline(job: Job) -> None:  
    try:  
        async with runtime.job_semaphore:  
            job.state = State.RUNNING  
            job.touch(); save_job(job)  
  
            tier = tier_for(getattr(job, "complexity", 3))  
            logger.info("[Job %s] complexity=%s -> tier=%s",  
                        job.id, getattr(job, "complexity", 3), tier)  
  
            gen_prompt = _GEN_PROMPT + job.prompt  
  
            or_on = job.stages.get("openrouter", True)  
            gq_on = job.stages.get("groq", True)  
            gm_on = job.stages.get("gemini", True)  
  
            # Mark every enabled agent as "working" up front so the UI shows  
            # all three spinning at once.  
            job.steps["generate_status"] = "working" if or_on else "done"  
            job.steps["verify_status"] = "working" if gq_on else "done"  
            job.steps["final_status"] = "working" if gm_on else "done"  
            job.touch(); save_job(job)  
  
            logger.info("[Job %s] Running OpenRouter, Groq, Gemini in parallel "  
                        "(tier=%s)...", job.id, tier)  
  
            # ---- All three agents work independently, at the same time. ----  
            (or_out, or_model), (gq_out, gq_model), (gm_out, gm_model) = \  
                await asyncio.gather(  
                    _run_agent(openrouter_generate, or_on, gen_prompt, tier,  
                               "[OpenRouter skipped]\n\n" + job.prompt),  
                    _run_agent(groq_generate, gq_on, gen_prompt, tier,  
                               "[Groq skipped]\n\n" + job.prompt),  
                    _run_agent(gemini_generate, gm_on, gen_prompt, tier,  
                               "[Gemini skipped]\n\n" + job.prompt),  
                )  
  
            # OpenRouter -> "generate" slot  
            job.steps["generate"] = or_out  
            job.steps["generate_model"] = or_model  
            job.steps["generate_status"] = "done"  
            # Groq -> "verify" slot  
            job.steps["verify"] = gq_out  
            job.steps["verify_model"] = gq_model  
            job.steps["verify_status"] = "done"  
            # Gemini -> "final" slot  
            job.steps["final"] = gm_out  
            job.steps["final_model"] = gm_model  
            job.steps["final_status"] = "done"  
            job.touch(); save_job(job)  
  
            # ---- Judge pool: averaged score for every agent's own output. ----  
            if job.stages.get("inkling", True):  
                logger.info("[Job %s] Judge pool scoring each agent...", job.id)  
                job.steps["summary_status"] = "working"  
                job.touch(); save_job(job)  
                candidates = [  
                    ("OpenRouter", "generate", or_out, or_on),  
                    ("Groq",       "verify",   gq_out, gq_on),  
                    ("Gemini",     "final",    gm_out, gm_on),  
                ]  
                scores = []  
                for name, key, output, ran in candidates:  
                    if not ran:  
                        job.steps[key + "_conf"] = ""  
                        continue  
                    try:  
                        pct = await judge_confidence(job.prompt, output)  
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
                    # Highest AVERAGE wins.  
                    scores.sort(reverse=True)  
                    best_pct, best_name, _best_key = scores[0]  
                    job.steps["summary"] = (  
                        f"Best is {best_name} because it scored the highest average "  
                        f"across the judge models against your request ({best_pct}%).")  
                    job.steps["summary_conf"] = str(best_pct)  
                else:  
                    job.steps["summary"] = "The judge pool could not score any agent."  
                    job.steps["summary_conf"] = ""  
                job.steps["summary_status"] = "done"  
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
