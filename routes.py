# DizerCore-AI  
# ----------------------------------------------------------------------------  
# routes.py — FastAPI route handlers.  
# Auth routes (/login, /register, /logout, /delete-account), app routes  
# (/, /run, /jobs, DELETE /jobs/{id}, /status, /status/stream, /stop,  
# /version, /favicon.ico).  
# Uploads are classified by extension: text files are folded into the prompt,  
# images/PDFs are kept raw on runtime.ATTACH for vision-capable providers,  
# .docx text is extracted dependency-free via zip+regex.  
import asyncio  
import base64  
import hmac  
import json  
import re  
import secrets  
import uuid  
import zipfile  
from io import BytesIO  
  
from fastapi import (  
    APIRouter, Form, File, UploadFile, HTTPException, Request, Response,  
)  
from fastapi.responses import (  
    HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse,  
)  
  
import runtime  
from config import (  
    MAX_PROMPT_CHARS, MAX_FILE_BYTES, MAX_TOTAL_FILE_BYTES, logger,  
    WEBUI_ADMIN_PASSWORD, classify_upload,  
)  
from db import (  
    State, Job,  
    save_job, delete_job_row, save_session, delete_session,  
    list_users, delete_user, delete_user_sessions, delete_user_jobs,  
)  
from auth import (  
    create_user, verify_user, current_user,  
    LOGIN_HTML, REGISTER_HTML, delete_account_html,  
)  
from pipeline import run_pipeline  
from web import DASHBOARD_HTML  
from version import get_version  
  
router = APIRouter()  
  
STREAM_INTERVAL = 0.15   # seconds between SSE flushes  
  
  
# ---------------------------------------------------------------------------  
# Routes: auth  
# ---------------------------------------------------------------------------  
@router.get("/login", response_class=HTMLResponse)  
async def login_page() -> str:  
    return LOGIN_HTML  
  
  
@router.post("/login")  
async def login(username: str = Form(...), password: str = Form(...)):  
    if not verify_user(username.strip(), password):  
        raise HTTPException(status_code=401, detail="Invalid username or password.")  
    token = secrets.token_urlsafe(32)  
    runtime.SESSIONS[token] = username.strip()  
    save_session(token, username.strip())  
    resp = RedirectResponse("/", status_code=303)  
    resp.set_cookie("dizer_session", token, httponly=True, samesite="lax")  
    return resp  
  
  
@router.get("/register", response_class=HTMLResponse)  
async def register_page() -> str:  
    return REGISTER_HTML  
  
  
@router.post("/register")  
async def register(username: str = Form(...), password: str = Form(...)):  
    username = username.strip()  
    if len(username) < 5 or len(password) < 8:  
        raise HTTPException(status_code=400,  
                            detail="Username min 5 chars, password min 8 chars.")  
    try:  
        create_user(username, password)  
    except ValueError as e:  
        raise HTTPException(status_code=400, detail=str(e))  
    logger.info("New user registered: %s", username)  
    return RedirectResponse("/login", status_code=303)  
  
  
@router.post("/logout")  
async def logout(request: Request):  
    token = request.cookies.get("dizer_session")  
    runtime.SESSIONS.pop(token or "", None)  
    delete_session(token or "")  
    resp = RedirectResponse("/login", status_code=303)  
    resp.delete_cookie("dizer_session")  
    return resp  
  
  
# ---------------------------------------------------------------------------  
# Routes: account deletion (admin-gated, no login required to reach the page)  
# ---------------------------------------------------------------------------  
@router.get("/delete-account", response_class=HTMLResponse)  
async def delete_account_page() -> str:  
    return delete_account_html()  
  
  
@router.post("/delete-account")  
async def delete_account(username: str = Form(...),  
                         admin_password: str = Form(...)):  
    # The install-time admin password is the ONLY gate — deleting is  
    # irreversible, so a wrong/empty password or unset env var refuses outright.  
    if not WEBUI_ADMIN_PASSWORD or not hmac.compare_digest(  
            admin_password.encode(), WEBUI_ADMIN_PASSWORD.encode()):  
        raise HTTPException(status_code=403, detail="Invalid admin password.")  
    username = username.strip()  
    if username not in list_users():  
        raise HTTPException(status_code=404, detail="User not found.")  
  
    # Cancel and drop the user's in-memory jobs, then purge all DB rows.  
    for jid, job in list(runtime.JOBS.items()):  
        if job.owner == username:  
            task = runtime.TASKS.get(jid)  
            if task and not task.done():  
                task.cancel()  
            runtime.JOBS.pop(jid, None)  
            runtime.TASKS.pop(jid, None)  
            runtime.ATTACH.pop(jid, None)  
    delete_user_jobs(username)  
    delete_user_sessions(username)  
    for tok, owner in list(runtime.SESSIONS.items()):  
        if owner == username:  
            runtime.SESSIONS.pop(tok, None)  
    delete_user(username)  
    logger.info("Admin deleted account: %s", username)  
    return RedirectResponse("/login", status_code=303)  
  
  
# ---------------------------------------------------------------------------  
# Routes: app  
# ---------------------------------------------------------------------------  
@router.get("/", response_class=HTMLResponse)  
async def index(request: Request):  
    token = request.cookies.get("dizer_session")  
    if not runtime.SESSIONS.get(token or ""):  
        return RedirectResponse("/login", status_code=303)  
    return HTMLResponse(DASHBOARD_HTML)  
  
  
@router.get("/version")  
async def version():  
    from version import get_info, check_remote  
    info = get_info()  
    remote = await check_remote()  
    return JSONResponse({  
        "version": info["sha"],  
        "installed_at": info["installed_at"],  
        "repo": info["repo"],  
        "latest": remote,  
        "update_available": bool(remote) and remote != info["sha"],  
    })
  
  
def _docx_text(raw: bytes) -> str:  
    """Pull text out of a .docx without external deps: the body is plain XML  
    inside word/document.xml — unzip, strip tags."""  
    try:  
        with zipfile.ZipFile(BytesIO(raw)) as z:  
            xml = z.read("word/document.xml").decode("utf-8", "replace")  
        xml = re.sub(r"</w:p>", "\n", xml)  
        return re.sub(r"<[^>]+>", "", xml).strip()  
    except Exception:  
        return ""  
  
  
@router.post("/run")  
async def run(  
    request: Request,  
    prompt: str = Form(...),  
    complexity: int = Form(3),  
    openrouter: str = Form("on"),  
    groq: str = Form("on"),  
    gemini: str = Form("on"),  
    inkling: str = Form("on"),  
    files: list[UploadFile] = File(default=[]),  
):  
    user = current_user(request)  
    prompt = prompt.strip()  
    if not prompt:  
        raise HTTPException(status_code=400, detail="Prompt is required.")  
  
    # Clamp complexity to the agreed 1-5 range (1-2 light, 3 normal, 4-5 heavy).  
    try:  
        complexity = int(complexity)  
    except (TypeError, ValueError):  
        complexity = 3  
    complexity = max(1, min(5, complexity))  
  
    # Classify uploads. Text/code/docx fold into the prompt as context;  
    # images and PDFs stay as raw bytes so vision-capable providers can  
    # read them (metadata lands on job.attachments, bytes on runtime.ATTACH).  
    total = 0  
    metas = []       # job.attachments — metadata only, must stay JSON-safe  
    raw_map = {}     # runtime.ATTACH[job_id] — filename -> bytes  
    for f in files:  
        raw = await f.read()  
        if not raw:  
            continue  
        total += len(raw)  
        if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_FILE_BYTES:  
            raise HTTPException(status_code=400, detail="Uploaded files too large.")  
        kind = classify_upload(f.filename or "")  
        mime = f.content_type or ""  
        if kind == "image":  
            metas.append({"name": f.filename, "kind": "image", "mime": mime})  
            raw_map[f.filename] = raw  
            prompt += f"\n\n[Attached image: {f.filename}]"  
        elif kind == "pdf":  
            metas.append({"name": f.filename, "kind": "pdf", "mime": mime})  
            raw_map[f.filename] = raw  
            prompt += f"\n\n[Attached PDF: {f.filename}]"  
        elif kind == "docx":  
            text = _docx_text(raw)  
            prompt += (f"\n\n--- FILE: {f.filename} ---\n{text}"  
                       if text else  
                       f"\n\n[Attached docx (unreadable): {f.filename}]")  
        else:  
            try:  
                text = raw.decode("utf-8")  
                prompt += f"\n\n--- FILE: {f.filename} ---\n{text}"  
            except UnicodeDecodeError:  
                prompt += (f"\n\n[Attached binary file: {f.filename} "  
                           f"({len(raw)} bytes)]")  
  
    if len(prompt) > MAX_PROMPT_CHARS:  
        raise HTTPException(status_code=400, detail="Prompt (with files) too large.")  
  
    job = Job(  
        id=uuid.uuid4().hex[:12],  
        owner=user,  
        prompt=prompt,  
        complexity=complexity,  
        attachments=metas,  
        stages={"openrouter": openrouter == "on",  
                "groq": groq == "on",  
                "gemini": gemini == "on",  
                "inkling": inkling == "on"},  
    )  
    runtime.JOBS[job.id] = job  
    if raw_map:  
        runtime.ATTACH[job.id] = raw_map  
    save_job(job)  
    runtime.TASKS[job.id] = asyncio.create_task(run_pipeline(job))  
    return JSONResponse({"job_id": job.id})  
  
  
@router.get("/jobs")  
async def jobs(request: Request):  
    user = current_user(request)  
    mine = [j for j in runtime.JOBS.values() if j.owner == user]  
    mine.sort(key=lambda j: j.created_at, reverse=True)  
    return JSONResponse([  
        {"id": j.id, "state": j.state, "created_at": j.created_at,  
         "title": (j.prompt[:60] + ("…" if len(j.prompt) > 60 else ""))}  
        for j in mine  
    ])  
  
  
@router.delete("/jobs/{job_id}")  
async def delete_job(job_id: str, request: Request):  
    user = current_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    task = runtime.TASKS.get(job_id)  
    if task and not task.done():  
        task.cancel()  
    runtime.JOBS.pop(job_id, None)  
    runtime.TASKS.pop(job_id, None)  
    runtime.ATTACH.pop(job_id, None)  
    delete_job_row(job_id)  
    return JSONResponse({"ok": True})  
  
  
@router.get("/status/{job_id}")  
async def status(job_id: str, request: Request):  
    user = current_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    return JSONResponse({  
        "id": job.id, "state": job.state, "error": job.error,  
        "complexity": job.complexity,  
        "steps": job.steps, "updated_at": job.updated_at,  
    })  
  
  
@router.get("/status/stream/{job_id}")  
async def status_stream(job_id: str, request: Request):  
    """SSE feed of job.steps deltas — every key whose text grew since the last  
    flush is emitted as {"key": ..., "delta": ...} so the browser appends  
    token-smooth instead of re-rendering the whole snapshot each poll."""  
    user = current_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
  
    async def gen():  
        sent = {k: 0 for k in job.steps}          # bytes already sent per key  
        while True:  
            if await request.is_disconnected():  
                break  
            for key, cur in job.steps.items():  
                if not isinstance(cur, str):  
                    continue  
                seen = sent.setdefault(key, 0)  
                if len(cur) > seen:  
                    delta = cur[seen:]  
                    sent[key] = len(cur)  
                    yield ("data: " + json.dumps(  
                        {"key": key, "delta": delta}) + "\n\n")  
            if job.state in (State.DONE, State.FAILED, State.CANCELLED):  
                yield ("data: " + json.dumps(  
                    {"key": "_done", "state": str(job.state)}) + "\n\n")  
                break  
            await asyncio.sleep(STREAM_INTERVAL)  
            yield ": keepalive\n\n"  
  
    return StreamingResponse(gen(), media_type="text/event-stream",  
                             headers={"Cache-Control": "no-cache"})  
  
  
@router.post("/stop/{job_id}")  
async def stop(job_id: str, request: Request):  
    user = current_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    task = runtime.TASKS.get(job_id)  
    if task and not task.done():  
        task.cancel()  
    runtime.ATTACH.pop(job_id, None)  
    return JSONResponse({"ok": True})  
  
  
@router.get("/favicon.ico")  
async def favicon() -> Response:  
    return Response(status_code=204)
