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
from config import (  
    MAX_PROMPT_CHARS, MAX_FILE_BYTES, MAX_TOTAL_FILE_BYTES,  
    WEBUI_ADMIN_PASSWORD, classify_upload, logger,  
)  
from auth import LOGIN_HTML, REGISTER_HTML  
from db import Job, State  
from pipeline import run_pipeline  
from web import DASHBOARD_HTML  
  
router = APIRouter()  
  
_COOKIE = "dizer_session"  
  
  
def current_user(request: Request) -> str:  
    token = request.cookies.get(_COOKIE, "")  
    return runtime.SESSIONS.get(token, "")  
  
  
def _require_user(request: Request) -> str:  
    user = current_user(request)  
    if not user:  
        raise HTTPException(status_code=401, detail="Not logged in.")  
    return user  
  
  
# ----------------------------------------------------------------------------  
# Auth  
# ----------------------------------------------------------------------------  
@router.get("/login", response_class=HTMLResponse)  
async def login_page():  
    return HTMLResponse(LOGIN_HTML)  
  
  
@router.post("/login")  
async def login(username: str = Form(""), password: str = Form("")):  
    if db.verify_user(username, password) or hmac.compare_digest(  
            password, WEBUI_ADMIN_PASSWORD):  
        token = secrets.token_hex(16)  
        runtime.SESSIONS[token] = username or "admin"  
        resp = RedirectResponse("/", status_code=303)  
        resp.set_cookie(_COOKIE, token, httponly=True, samesite="lax")  
        return resp  
    raise HTTPException(status_code=401, detail="Bad credentials.")  
  
  
@router.get("/register", response_class=HTMLResponse)  
async def register_page():  
    return HTMLResponse(REGISTER_HTML)  
  
  
@router.post("/register")  
async def register(username: str = Form(""), password: str = Form("")):  
    if db.create_user(username, password):  
        logger.info("New user registered: %s", username)  
        return RedirectResponse("/login", status_code=303)  
    raise HTTPException(status_code=400, detail="Username taken or invalid.")  
  
  
@router.get("/logout")  
async def logout(request: Request):  
    token = request.cookies.get(_COOKIE, "")  
    runtime.SESSIONS.pop(token, None)  
    resp = RedirectResponse("/login", status_code=303)  
    resp.delete_cookie(_COOKIE)  
    return resp  
  
  
@router.post("/delete-account")  
async def delete_account(request: Request):  
    user = _require_user(request)  
    db.delete_user(user)  
    token = request.cookies.get(_COOKIE, "")  
    runtime.SESSIONS.pop(token, None)  
    return RedirectResponse("/login", status_code=303)  
  
  
# ----------------------------------------------------------------------------  
# App  
# ----------------------------------------------------------------------------  
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
    if len(prompt) > MAX_PROMPT_CHARS:  
        raise HTTPException(status_code=400, detail="Prompt too long.")  
    complexity = max(1, min(5, int(complexity)))  
  
    total = 0  
    runtime.ATTACH  # ensure dict exists  
    job_id = uuid.uuid4().hex[:12]  
    attach = []  
    for f in files or []:  
        data = await f.read()  
        if not data:  
            continue  
        total += len(data)  
        if len(data) > MAX_FILE_BYTES:  
            raise HTTPException(status_code=400,  
                                detail=f"{f.filename} exceeds file size limit.")  
        if total > MAX_TOTAL_FILE_BYTES:  
            raise HTTPException(status_code=400,  
                                detail="Total upload size exceeded.")  
        kind, text = classify_upload(f.filename or "", data)  
        if kind == "text":  
            prompt += f"\n\n--- {f.filename} ---\n{text}"  
        else:  
            attach.append({"name": f.filename or "file", "kind": kind,  
                           "mime": f.content_type or "", "data": data})  
    runtime.ATTACH[job_id] = attach  
  
    job = Job(  
        id=job_id,  
        prompt=prompt,  
        complexity=complexity,  
        owner=user,  
        state=State.RUNNING,  
        stages={"openrouter": openrouter == "on",  
                "groq": groq == "on",  
                "gemini": gemini == "on",  
                "inkling": inkling == "on"},  
    )  
    runtime.JOBS[job.id] = job  
    db.save_job(job)  
    runtime.TASKS[job.id] = asyncio.create_task(run_pipeline(job))  
    return JSONResponse({"job_id": job.id})  
  
  
@router.get("/jobs")  
async def jobs(request: Request):  
    user = _require_user(request)  
    mine = [j for j in runtime.JOBS.values() if j.owner == user]  
    mine.sort(key=lambda j: j.created_at, reverse=True)  
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
        raise HTTPException(status_code=404, detail="No such job.")  
    task = runtime.TASKS.get(job_id)  
    if task and not task.done():  
        task.cancel()  
    runtime.JOBS.pop(job_id, None)  
    runtime.ATTACH.pop(job_id, None)  
    delete = getattr(db, "delete_job", None)  
    if delete:  
        delete(job_id)  
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
        raise HTTPException(status_code=404, detail="No such job.")  
    return JSONResponse(_job_payload(job))  
  
  
@router.get("/status/stream/{job_id}")  
async def status_stream(job_id: str, request: Request):  
    user = _require_user(request)  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="No such job.")  
  
    async def gen():  
        last = None  
        while True:  
            payload = _job_payload(job)  
            blob = json.dumps(payload, default=str)  
            if blob != last:  
                last = blob  
                yield f"data: {blob}\n\n"  
            if job.state in (State.DONE, State.FAILED, State.CANCELLED):  
                break  
            await asyncio.sleep(0.4)  
  
    return StreamingResponse(gen(), media_type="text/event-stream")  
  
  
def _cancel_job(job_id: str, user: str):  
    job = runtime.JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="No such job.")  
    task = runtime.TASKS.get(job_id)  
    if task and not task.done():  
        task.cancel()  
        logger.info("[Job %s] cancel requested by %s", job_id, user)  
    elif job.state == State.RUNNING:  
        job.state = State.CANCELLED  
        for k in ("generate", "verify", "final", "summary"):  
            if job.steps.get(k + "_status") == "working":  
                job.steps[k + "_status"] = "cancelled"  
        db.save_job(job)  
    return JSONResponse({"ok": True})  
  
  
@router.post("/stop/{job_id}")  
async def stop(job_id: str, request: Request):  
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
