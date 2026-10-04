# DizerCore-AI  
# ----------------------------------------------------------------------------  
# pipeline.py — the 3-agent pipeline runner.  
# ChatGPT (OpenAI), Groq, Gemini each INDEPENDENTLY write code in parallel —  
# no cross-checking. Jobs always start at level 1 (light tier) and  
# auto-escalate 1->2->3 (light->normal->heavy) on build failures, capped at  
# MAX_LEVEL.  
#  
# Judging (OpenRouter-only pool) starts as soon as EACH agent finishes.  
# Judge access is serialized per job through an asyncio.Lock so the dedicated  
# judge key still sees strictly serial, JUDGE_DELAY-spaced calls. Each  
# candidate starts at a rotated JUDGE_MODELS index (ChatGPT->0, Gemini->1,  
# Groq->last), wrapping through the pool until a usable score lands.  
# The highest score wins the summary; judge[0] then runs a confirmation pass.  
#  
# GUARDRAILS: if the entire judge pool fails, a fallback winner is picked  
# (first non-skip output in generate/verify/final order) so downstream build  
# stages always have something to work with. The build payload is produced  
# ONLY through guardrails.build_package — fenced code blocks, no prose,  
# no judge comments (summary is never a build input).  
#  
# REMOTE BUILD: when BUILD_ENABLED + BUILD_HOST are set, the extracted  
# package is rsynced to the tadashi executor and built under prlimit + bwrap.  
# A failed remote build counts as a failed build attempt and drives the same  
# 1->2->3 escalation loop as a failed extraction (capped by  
# min(BUILD_MAX_RETRIES, MAX_LEVEL - 1)).  
import asyncio  
import os  
import shlex  
import tempfile  
  
import config  
import runtime  
import guardrails  
from config import JUDGE_MODELS, MAX_LEVEL, logger, tier_for  
from db import State, save_job  
from providers import (  
    gemini_generate, groq_generate, judge_confidence, openai_generate,  
)  
  
_TIER_ORDER = ("light", "normal", "heavy")  
_AGENT_FNS = {"generate": openai_generate, "verify": groq_generate,  
              "final": gemini_generate}  
_LEVEL_NAMES = {1: "simple", 2: "normal", 3: "difficult"}  
  
  
async def _run_agent(fn, enabled: bool, prompt: str, tier: str,  
                     skip_msg: str, job, key: str):  
    if not enabled:  
        return skip_msg, ""  
    return await fn(prompt, tier=tier, job=job, key=key)  
  
  
def _is_skip(out: str) -> bool:  
    """True if the output is a skip/junk marker rather than real code —  
    don't spend a judge call on it."""  
    return (out or "").startswith("[")  
  
  
async def _judge_candidate(job, name, key, out, ran, lock, start_index):  
    """Judge one finished candidate under the serial judge lock."""  
    if not ran or _is_skip(out):  
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
    out, model = await _run_agent(fn, enabled, prompt, tier, skip_msg,  
                                  job, key)  
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
    """Highest score wins; ties go to the earliest-finished candidate.  
    Records _winner_key so the build stage knows which RAW output to feed  
    guardrails — summary itself has judge comments appended and is NEVER  
    used as a build input."""  
    if not scores:  
        return  
    key, conf = max(scores, key=lambda kv: kv[1])  
    job.steps["_winner_key"] = key  
    job.steps["summary"] = job.steps.get(key, "")  
    job.steps["summary_conf"] = str(conf)  
    comments = job.steps.get(key + "_judge_comments") or ""  
    if comments:  
        job.steps["summary"] += "\n\n" + comments  
  
  
def _fallback_winner(job) -> str | None:  
    """Judge pool dead or all outputs skipped — still hand the build stage  
    the best available raw output: first non-skip in generate/verify/final  
    order. Returns the key or None if literally nothing was produced."""  
    for key in ("generate", "verify", "final"):  
        out = job.steps.get(key) or ""  
        if out and not _is_skip(out):  
            job.steps["_winner_key"] = key  
            job.steps["summary"] = (  
                out + "\n\n(unjudged — judge pool produced no usable score)")  
            job.steps["summary_conf"] = ""  
            return key  
    return None  
  
  
def _skip_build(job):  
    job.steps["build_ready"] = ""  
    job.steps["build_status"] = "skipped"  
    job.steps["build_output"] = (  
        "No runnable code extracted from agent output "  
        "(all responses were prose or empty).")  
  
  
# ----------------------------------------------------------------------------  
# Remote build executor (tadashi) — see install-executor.sh for the host-side  
# contract. Edith side only ever calls ssh/rsync as argument arrays; the one  
# shell string on the remote side runs inside prlimit + bwrap.  
# ----------------------------------------------------------------------------  
  
def _ssh_base() -> list[str]:  
    """ssh argv prefix used for every tadashi call."""  
    return ["ssh", "-i", config.BUILD_KEY_PATH, "-o", "BatchMode=yes",  
            "-o", "ConnectTimeout=10", "-o",  
            "StrictHostKeyChecking=accept-new",  
            f"{config.BUILD_USER}@{config.BUILD_HOST}"]  
  
  
def _rsync_ssh() -> str:  
    """rsync -e shell string (rsync needs a string, not argv)."""  
    return ("ssh -i " + shlex.quote(config.BUILD_KEY_PATH)  
            + " -o BatchMode=yes -o StrictHostKeyChecking=accept-new")  
  
  
def _remote_enabled(job) -> bool:  
    return (bool(job.stages.get("build"))  
            and config.BUILD_ENABLED and bool(config.BUILD_HOST))  
  
  
def _default_build_cmd() -> str:  
    """Fallback remote build command when the user gave no build_cmd."""  
    return ("if [ -f Makefile ]; then make -j" + str(config.BUILD_JOBS) +  
            "; elif ls *.py >/dev/null 2>&1; then python3 -m py_compile *.py"  
            "; elif ls *.c >/dev/null 2>&1; then cc -O2 -o app *.c"  
            "; else echo 'no known build target'; exit 2; fi")  
  
  
def _remote_cmd(job, jobdir: str, tree: bool) -> str:  
    """Single remote shell string: prep the job dir (clone in tree mode),  
    then run the build under prlimit + bwrap with cwd inside the sandbox."""  
    cmd = (job.stages.get("build_cmd") or "").strip() or _default_build_cmd()  
    if tree:  
        repo = job.stages["build_repo"].strip()  
        prep = (f"mkdir -p {shlex.quote(jobdir)} && cd {shlex.quote(jobdir)}"  
                f" && git clone {shlex.quote(repo)} src 2>/dev/null"  
                f" || git clone {shlex.quote(config.BUILD_ROOT + '/repo.git')}"  
                " src; cd src && "  
                "[ -f ../changes.diff ] && git apply ../changes.diff; "  
                "true")  
        workdir = f"{jobdir}/src"  
    else:  
        prep = f"mkdir -p {shlex.quote(jobdir)}"  
        workdir = jobdir  
    sandbox = (f"prlimit --as={config.BUILD_MEM_MB}m "  
               f"--cpu={config.BUILD_CPU_S} "  
               "bwrap --unshare-all --dev /dev --proc /proc "  
               f"--bind {shlex.quote(workdir)} /work --chdir /work "  
               f"--setenv MAKEFLAGS -j{config.BUILD_JOBS} "  
               f"-- /bin/sh -lc {shlex.quote(cmd)}")  
    return prep + " && " + sandbox  
  
  
async def _ship_files(job, pkg: dict, jobdir: str) -> tuple[bool, str]:  
    """rsync the extracted package files into the tadashi job dir."""  
    try:  
        with tempfile.TemporaryDirectory() as td:  
            for rel, body in pkg["files"].items():  
                dest = os.path.join(td, rel)  
                os.makedirs(os.path.dirname(dest) or td, exist_ok=True)  
                with open(dest, "w") as fh:  
                    fh.write(body)  
            proc = await asyncio.create_subprocess_exec(  
                "rsync", "-az", "--delete", "-e", _rsync_ssh(), td + "/",  
                f"{config.BUILD_USER}@{config.BUILD_HOST}:{jobdir}/",  
                stdout=asyncio.subprocess.PIPE,  
                stderr=asyncio.subprocess.STDOUT)  
            out, _ = await asyncio.wait_for(proc.communicate(), 120)  
            if proc.returncode != 0:  
                return False, "rsync failed:\n" + (out or b"").decode(  
                    errors="replace")[-2000:]  
            return True, ""  
    except asyncio.TimeoutError:  
        proc.kill()  
        return False, "rsync timed out after 120s"  
    except Exception as e:  # noqa: BLE001  
        return False, f"rsync dispatch error: {e}"  
  
  
async def _remote_build(job, pkg: dict) -> tuple[bool, str]:  
    """Ship the package to tadashi and run the build under prlimit + bwrap.  
    Returns (ok, log_tail). Never raises."""  
    jobdir = f"{config.BUILD_ROOT}/jobs/{job.id}"  
    tree = bool((job.stages.get("build_repo") or "").strip())  
    timeout = config.BUILD_TIMEOUT_TREE if tree else config.BUILD_TIMEOUT_S  
  
    if not tree:  
        ok, log = await _ship_files(job, pkg, jobdir)  
        if not ok:  
            return False, log  
    elif pkg["files"].get("changes.diff"):  
        # Tree mode: push just the diff so the remote can `git apply` it.  
        proc = await asyncio.create_subprocess_exec(  
            *_ssh_base(),  
            f"mkdir -p {shlex.quote(jobdir)} && cat > "  
            f"{shlex.quote(jobdir)}/changes.diff",  
            stdin=asyncio.subprocess.PIPE,  
            stdout=asyncio.subprocess.PIPE,  
            stderr=asyncio.subprocess.STDOUT)  
        out, _ = await asyncio.wait_for(  
            proc.communicate(pkg["files"]["changes.diff"].encode()), 60)  
        if proc.returncode != 0:  
            return False, "diff upload failed:\n" + (out or b"").decode(  
                errors="replace")[-2000:]  
  
    try:  
        proc = await asyncio.create_subprocess_exec(  
            *_ssh_base(), _remote_cmd(job, jobdir, tree),  
            stdout=asyncio.subprocess.PIPE,  
            stderr=asyncio.subprocess.STDOUT)  
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)  
        return proc.returncode == 0, (out or b"").decode(  
            errors="replace")[-4000:]  
    except asyncio.TimeoutError:  
        proc.kill()  
        return False, f"remote build timed out after {timeout}s"  
    except Exception as e:  # noqa: BLE001  
        return False, f"remote dispatch error: {e}"  
  
  
async def _prepare_build(job):  
    """Guardrail gate + auto-escalating repair loop: turn the winning RAW  
    output into a clean code package and, when BUILD_ENABLED + BUILD_HOST  
    are set, prove it compiles/runs on tadashi. On each failed attempt  
    (extraction OR remote build) the job level is bumped 1->2->3  
    (light->normal->heavy, capped at MAX_LEVEL and BUILD_MAX_RETRIES) and  
    the winning agent regenerates its output at the new tier. Writes  
    job.steps['build_ready'], 'build_status', 'build_output' (+  
    'build_level' on escalation). Never raises; never lets prose/comments  
    leave the box as 'code'."""  
    winner_key = job.steps.get("_winner_key")  
    raw = job.steps.get(winner_key) if winner_key else ""  
    remote = _remote_enabled(job)  
    max_attempts = min(config.BUILD_MAX_RETRIES, MAX_LEVEL - 1) + 1  
  
    if not job.stages.get("build"):  
        # No build stage enabled — single extraction pass, level stays 1.  
        pkg = guardrails.build_package(raw or "")  
        if pkg is None:  
            _skip_build(job)  
            return  
        job.steps["build_ready"] = "\n\n".join(pkg["files"].values())  
        job.steps["build_status"] = "ready"  
        return  
  
    gen_fn = _AGENT_FNS.get(winner_key)  
    attempt = 0  
    while True:  
        attempt += 1  
        pkg = guardrails.build_package(raw or "")  
        if pkg is not None:  
            job.steps["build_ready"] = "\n\n".join(pkg["files"].values())  
            if not remote:  
                job.steps["build_status"] = "ready"  
                logger.info("[Job %s] build package: %d file(s) at level "  
                            "%d.", job.id, len(pkg["files"]), job.complexity)  
                return  
            ok, log = await _remote_build(job, pkg)  
            job.steps["build_output"] = log  
            job.touch(); save_job(job)  
            if ok:  
                job.steps["build_status"] = "passed"  
                logger.info("[Job %s] remote build passed at level %d.",  
                            job.id, job.complexity)  
                return  
            logger.info("[Job %s] remote build attempt %d failed at level "  
                        "%d.", job.id, attempt, job.complexity)  
        # Attempt failed — escalate level and retry at a higher tier.  
        if (attempt >= max_attempts or job.complexity >= MAX_LEVEL  
                or gen_fn is None):  
            if pkg is None:  
                _skip_build(job)  
            else:  
                job.steps["build_status"] = "failed"  
            logger.info("[Job %s] build ended at level %d after %d "  
                        "attempt(s).", job.id, job.complexity, attempt)  
            return  
        job.complexity = min(job.complexity + 1, MAX_LEVEL)  
        tier = _TIER_ORDER[job.complexity - 1]  
        job.steps["build_level"] = (  
            f"build attempt {attempt} failed — escalating to "  
            f"{_LEVEL_NAMES[job.complexity]} tier "  
            f"(level {job.complexity})")  
        job.touch(); save_job(job)  
        logger.info("[Job %s] escalating to level %d (%s tier).",  
                    job.id, job.complexity, tier)  
        out, _model = await gen_fn(job.prompt, tier=tier, job=job,  
                                   key=winner_key)  
        if out and not _is_skip(out):  
            raw = out  
            job.steps[winner_key] = out  
            job.touch(); save_job(job)  
  
  
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
  
        # return_exceptions=True: one agent blowing up must NOT cancel the  
        # other two mid-write. Failed agents land as exceptions in `results`.  
        results = await asyncio.gather(  
            _agent_then_judge(job, openai_generate,  
                              job.stages.get("openai", True),  
                              gen_prompt, tier,  
                              "[ChatGPT skipped]\n\n" + job.prompt,  
                              "ChatGPT", "generate", 0, lock, scores),  
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
            return_exceptions=True,  
        )  
        for r in results:  
            if isinstance(r, Exception) and not isinstance(  
                    r, asyncio.CancelledError):  
                logger.error("[Job %s] agent task failed: %s", job.id, r)  
  
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
                _fallback_winner(job)  
            job.steps["summary_status"] = "done"  
        else:  
            # Judging disabled — still need a winner for the build gate.  
            _fallback_winner(job)  
        job.touch(); save_job(job)  
  
        await _prepare_build(job)  
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
  
  
async def run_pipeline(job):  
    """Entrypoint called by routes.py — wraps run_job by id."""  
    await run_job(job.id)
