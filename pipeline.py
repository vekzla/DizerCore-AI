# DizerCore-AI  
# ----------------------------------------------------------------------------  
# pipeline.py — the 3-agent pipeline runner.  
# OpenRouter, Groq, Gemini each INDEPENDENTLY write code in parallel — no  
# cross-checking. Complexity 1-5 picks ONE tier: 1-2 light, 3 normal, 4-5 heavy.  
#  
# Judging starts as soon as EACH agent finishes (not after all three). Judge  
# access is serialized per job through an asyncio.Lock so the dedicated judge  
# key still sees strictly serial, JUDGE_DELAY-spaced calls. Each candidate  
# starts at a rotated JUDGE_MODELS index (OpenRouter->0, Gemini->1,  
# Groq->last), wrapping through the pool until a usable score lands.  
# The highest score wins the summary; judge[0] then runs a confirmation pass.  
import asyncio  
  
import runtime  
from config import JUDGE_MODELS, logger, tier_for  
from db import State, save_job  
from providers import (  
    gemini_generate, groq_generate, judge_confidence, openrouter_generate,  
)  
  
  
async def _run_agent(fn, enabled: bool, prompt: str, tier: str,  
                     skip_msg: str, job, key: str):  
    if not enabled:  
        return skip_msg, ""  
    return await fn(prompt, tier=tier, job=job, key=key)  
  
  
async def _judge_candidate(job, name, key, out, ran, lock, start_index):  
    """Judge one finished candidate under the serial judge lock."""  
    if not ran:  
        job.steps[key + "_conf"] = ""  
        job.steps[key + "_judge_comments"] = ""  
        return None  
    async with lock:  
        conf, comments = await judge_confidence(  
            job.prompt, out, start_index=start_index)  
    job.steps[key + "_conf"] = conf  
    job.steps[key + "_judge_comments"] = comments  
    if conf:  
        logger.info("[Job %s] %s scored %s.", job.id, name, conf)  
    else:  
        logger.info("[Job %s] %s got no usable judge score.", job.id, name)  
    return (key, int(conf)) if conf else None  
  
  
async def _agent_then_judge(job, fn, enabled, prompt, tier, skip_msg,  
                            name, key, judge_start, lock, scores):  
    """Generate -> write slot -> judge immediately (serialized by lock)."""  
    out, model = await _run_agent(fn, enabled, prompt, tier, skip_msg, job, key)  
    if job.steps.get(key) != out:   # streamed deltas may already be there  
        job.steps[key] = out  
    job.steps[key + "_model"] = model  
    job.steps[key + "_status"] = "done"  
    job.touch(); save_job(job)  
    if enabled and job.stages.get("inkling", True):  
        result = await _judge_candidate(job, name, key, out, enabled,  
                                        lock, judge_start)  
        if result is not None:  
            scores.append(result)  
        job.touch(); save_job(job)  
  
  
def _pick_winner(job, scores):  
    """Highest score wins; ties go to the earliest-finished candidate."""  
    if not scores:  
        return  
    key, conf = max(scores, key=lambda kv: kv[1])  
    job.steps["summary"] = job.steps.get(key, "")  
    job.steps["summary_conf"] = str(conf)  
    comments = job.steps.get(key + "_judge_comments") or ""  
    if comments:  
        job.steps["summary"] += "\n\n" + comments  
  
  
async def run_job(job_id: str):  
    job = runtime.JOBS.get(job_id)  
    if not job:  
        return  
    try:  
        job.state = State.RUNNING  
        job.touch(); save_job(job)  
  
        tier = tier_for(job.complexity)  
        gen_prompt = job.prompt  
  
        for k in ("generate", "verify", "final"):  
            job.steps[k] = ""  
            job.steps[k + "_thinking"] = ""  
            job.steps[k + "_status"] = "working"  
        if job.stages.get("inkling", True):  
            job.steps["summary"] = "Judging each agent as it finishes..."  
            job.steps["summary_status"] = "working"  
        job.touch(); save_job(job)  
  
        lock = asyncio.Lock()  
        scores = []  
        last = max(len(JUDGE_MODELS) - 1, 0)  
  
        await asyncio.gather(  
            _agent_then_judge(job, openrouter_generate,  
                              job.stages.get("openrouter", True),  
                              gen_prompt, tier,  
                              "[OpenRouter skipped]\n\n" + job.prompt,  
                              "OpenRouter", "generate", 0, lock, scores),  
            _agent_then_judge(job, groq_generate,  
                              job.stages.get("groq", True),  
                              gen_prompt, tier,  
                              "[Groq skipped]\n\n" + job.prompt,  
                              "Groq", "verify", last, lock, scores),  
            _agent_then_judge(job, gemini_generate,  
                              job.stages.get("gemini", True),  
                              gen_prompt, tier,  
                              "[Gemini skipped]\n\n" + job.prompt,  
                              "Gemini", "final", 1, lock, scores),  
        )  
  
        if job.stages.get("inkling", True):  
            _pick_winner(job, scores)  
            # Final confirmation pass by the BEST judge on the winner.  
            if scores and job.steps.get("summary"):  
                async with lock:  
                    conf2, _c = await judge_confidence(  
                        job.prompt, job.steps["summary"], start_index=0)  
                if conf2:  
                    job.steps["summary_conf"] = conf2  
            if not scores:  
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
        runtime.ATTACH.pop(job.id, None)  
        runtime.TASKS.pop(job.id, None)
