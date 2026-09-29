# DizerCore-AI  
# ----------------------------------------------------------------------------  
# routes.py — FastAPI route handlers.  
# Auth routes (/login, /register, /logout, /delete-account), app routes  
# (/, /run, /jobs, DELETE /jobs/{id}, /status, /status/stream, /stop,  
# /version, /favicon.ico). Shared job/session state lives on runtime.*  
# (populated at startup by lifespan).  
import asyncio  
import hmac  
import json  
import secrets  
import uuid  
  
from fastapi import (  
    APIRouter, Form, File, UploadFile, HTTPException, Request, Response,  
)  
from fastapi.responses import (  
    HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse,  
)  
  
import runtime  
import version  
import db  
from config import WEBUI_ADMIN_PASSWORD as ADMIN_PASSWORD, logger  
from auth import (  
    LOGIN_HTML, REGISTER_HTML, delete_account_html,  
    current_user, COOKIE_NAME,  
)  
from db import Job, State  
from pipeline import run_pipeline  
from web import DASHBOARD_HTML  
  
router = APIRouter()  
  
  
# -----------------------------------------------------------------------------  
# Helpers  
# -----------------------------------------------------------------------------  
def _require_user(request: Request) -> str:  
    user = current_user(request)  
    if not user:  
        raise HTTPException(status_code=401, detail="Login required.")  
    return user  
  
  
# -----------------------------------------------------------------------------  
# Auth pages  
# -----------------------------------------------------------------------------  
@router.get("/login", response_class=HTMLResponse)  
async def login_page(request: Request):  
    if current_user(request):  
        return RedirectResponse("/", status_code=303)  
    return HTMLResponse(LOGIN_HTML)  
  
  
@router.post("/login")  
async def login(username: str = Form(""), password: str = Form("")):  
    username = username.strip()  
    if not db.verify_user(username, password):  
        raise HTTPException(status_code=401, detail="Invalid username or password.")  
    token = secrets.token_hex(24)  
    runtime.SESSIONS[token] = username  
    db.save_session(token, username)  
    logger.info("User logged in: %s", username)  
    resp = RedirectResponse("/", status_code=303)  
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")  
    return resp  
  
  
@router.get("/register", response_class=HTMLResponse)  
async def register_page(request: Request):  
    if current_user(request):  
        return RedirectResponse("/", status_code=303)  
    return HTMLResponse(REGISTER_HTML)  
  
  
@router.post("/register")  
async def register(request: Request, username: str = Form(""),  
                   password: str = Form("")):  
    username = username.strip()  
    if not username or not password:  
        raise HTTPException(status_code=400, detail="Username and password required.")  
    try:  
        db.create_user(username, password)  
    except ValueError:  
        raise HTTPException(status_code=400, detail="Username taken or invalid.")  
    logger.info("New user registered: %s", username)  
    # Auto-login on success — bounce straight to the dashboard, not the login page.  
    token = secrets.token_hex(24)  
    runtime.SESSIONS[token] = username  
    db.save_session(token, username)  
    resp = RedirectResponse("/", status_code=303)  
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")  
    return resp  
  
  
@router.get("/logout")  
async def logout(request: Request):  
    token = request.cookies.get(COOKIE_NAME, "")  
    user = runtime.SESSIONS.pop(token, None)  
    if token:  
        db.delete_session(token)  
    if user:  
        logger.info("User logged out: %s", user)  
    resp = RedirectResponse("/login", status_code=303)  
    resp.delete_cookie(COOKIE_NAME)  
    return resp  
  
  
@router.get("/delete-account", response_class=HTMLResponse)  
async def delete_account_page(request: Request):  
    # Page route: redirect to /login on no session, not a raw 401.  
    if not current_user(request):  
        return RedirectResponse("/login", status_code=303)  
    return HTMLResponse(delete_account_html())  
  
  
@router.post("/delete-account")  
async def delete_account(request: Request, username: str = Form(""),  
                         admin_password: str = Form("")):  
    _require_user(request)  
    if not hmac.compare_digest(admin_password, ADMIN_PASSWORD or ""):  
        raise HTTPException(status_code=403, detail="Bad admin password.")  
    if username not in db.list_users():  
        raise HTTPException(status_code=404, detail="Unknown user.")  
    db.delete_user(username)  
    db.delete_user_sessions(username)  
    db.delete_user_jobs(username)  
    for tok, uname in list(runtime.SESSIONS.items()):  
        if uname == username:  
            runtime.SESSIONS.pop(tok, None)  
    for jid, job in list(runtime.JOBS.items()):  
        if job.owner == username:  
            runtime.JOBS.pop(jid, None)  
            runtime.ATTACH.pop(jid, None)  
            t = runtime.TASKS.pop(jid, None)  
            if t:  
                t.cancel()  
    logger.info("Account deleted: %s", username)  
    resp = RedirectResponse("/login", status_code=303)  
    resp.delete_cookie(COOKIE_NAME)  
    return resp  
  
  
# -----------------------------------------------------------------------------  
# App routes  
# -----------------------------------------------------------------------------  
@router.get("/", response_class=HTMLResponse)  
async def index(request: Request):  
    if not current_user(request):  
        return RedirectResponse("/login", status_code=303)  
    return HTMLResponse(DASHBOARD_HTML)  
  
  
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
    user = _require_user(request)  
    prompt = prompt.strip()  
    if not prompt:  
        raise HTTPException(status_code=400, detail="Prompt is required.")  
  
    job = Job(  
        id=uuid.uuid4().hex[:12],  
        owner=user,  
        prompt=prompt,  
        complexity=max(1, min(5, complexity)),  
        stages={"openrouter": openrouter == "on",  
                "groq": groq == "on",  
                "gemini": gemini == "on",  
                "inkling": inkling == "on"},  
    )  
  
    for f in files or []:  
        if not f.filename:  
            continue  
        data = await f.read()  
        if not data:  
            continue  
        job.attachments.append(f.filename)  
        runtime.ATTACH.setdefault(job.id, []).append((f.filename, data))  
  
    runtime.JOBS[job.id] = job  
    db.save_job(job)  
    runtime.TASKS[job.id] = asyncio.create_task(run_pipeline(job))  
    logger.info("[Job %s] queued by %s", job.id, user)  
    return JSONResponse({"job_id": job.id})  
  
  
@router.get("/jobs")  
async def list_jobs(request: Request):  
    user = _require_user(request)  
    mine = sorted(  
        (j for j in runtime.JOBS.values() if j.owner == user),  
        key=lambda j: j.created_at, reverse=True,  
    )  
    return JSONResponse([  
        {"id": j.id, "state": j.state, "created_at": j.created_at,  
         "title": (j.prompt[:60] + ("…" if len(j.prompt) > 60 else ""))}  
        for j in mine  
    ])  
  
  
@router.delete("/jobs/{job_id}")  
async def delete_job(job_id: str, request: Request):  
    user = _require_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    t = runtime.TASKS.pop(job_id, None)  
    if t:  
        t.cancel()  
    runtime.JOBS.pop(job_id, None)  
    runtime.ATTACH.pop(job_id, None)  
    db.delete_job_row(job_id)  
    return JSONResponse({"ok": True})  
  
  
def _job_payload(job: Job) -> dict:  
    return {  
        "id": job.id, "state": job.state, "error": job.error,  
        "complexity": job.complexity,  
        "steps": job.steps, "updated_at": job.updated_at,  
    }  
  
  
@router.get("/status/{job_id}")  
async def status(job_id: str, request: Request):  
    user = _require_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    return JSONResponse(_job_payload(job))  
  
  
@router.get("/status/stream/{job_id}")  
async def status_stream(job_id: str, request: Request):  
    user = _require_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
  
    async def gen():  
        last = ""  
        while True:  
            if await request.is_disconnected():  
                return  
            payload = _job_payload(job)  
            blob = json.dumps(payload, default=str)  
            if blob != last:  
                last = blob  
                yield f"data: {blob}\n\n"  
            if job.state in (State.DONE, State.FAILED, State.CANCELLED):  
                return  
            await asyncio.sleep(0.4)  
  
    return StreamingResponse(gen(), media_type="text/event-stream")  
  
  
def _cancel_job(job_id: str, user: str):  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    if job.state in (State.DONE, State.FAILED, State.CANCELLED):  
        return JSONResponse({"ok": True, "state": job.state})  
    t = runtime.TASKS.get(job_id)  
    if t:  
        t.cancel()  
    else:  
        job.state = State.CANCELLED  
        job.error = "Cancelled by user."  
        job.touch()  
        db.save_job(job)  
    logger.info("[Job %s] cancel requested by %s", job_id, user)  
    return JSONResponse({"ok": True})  
  
  
@router.post("/stop/{job_id}")  
async def stop_post(job_id: str, request: Request):  
    return _cancel_job(job_id, _require_user(request))  
  
  
@router.get("/stop/{job_id}")  
async def stop_get(job_id: str, request: Request):  
    # Some frontends fire a plain GET/navigation for stop — accept it too.  
    return _cancel_job(job_id, _require_user(request))  
  
  
@router.post("/stop")  
async def stop_query(request: Request, job_id: str = Form("")):  
    # Fallback for frontends that POST the id as a form/query field.  
    jid = job_id or request.query_params.get("job_id", "") or request.query_params.get("id", "")  
    if not jid:  
        raise HTTPException(status_code=400, detail="job_id required.")  
    return _cancel_job(jid, _require_user(request))  
  
  
@router.get("/version")  
async def version_info():  
    info = version.get_info()  
    latest = await version.check_remote()  
    sha = info.get("sha", "unknown")  
    return JSONResponse({  
        "version": sha,  
        "installed_at": info.get("installed_at", ""),  
        "repo": info.get("repo", ""),  
        "latest": latest,  
        "update_available": bool(latest) and latest != sha,  
    })  
  
  
@router.get("/favicon.ico")  
async def favicon() -> Response:  
    return Response(status_code=204)
