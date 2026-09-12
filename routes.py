# routes.py  
# DizercoreAI — FastAPI route handlers.  
# Auth routes (/login, /register, /logout), app routes (/, /run, /jobs,  
# DELETE /jobs/{id}, /status, /stop, /favicon.ico).  
# Wired to pipeline.run_pipeline and the per-job complexity (1-5) selector.  
import asyncio  
import secrets  
import uuid  
  
from fastapi import (  
    APIRouter, Form, File, UploadFile, HTTPException, Request, Response,  
)  
from fastapi.responses import (  
    HTMLResponse, JSONResponse, RedirectResponse,  
)  
  
from config import (  
    MAX_PROMPT_CHARS, MAX_FILE_BYTES, MAX_TOTAL_FILE_BYTES, logger,  
)  
from db import (  
    State, Job, JOBS, TASKS, SESSIONS,  
    save_job, delete_job_row, save_session, delete_session,  
)  
from auth import (  
    create_user, verify_user, current_user,  
    LOGIN_HTML, REGISTER_HTML,  
)  
from pipeline import run_pipeline  
from web import DASHBOARD_HTML  
  
router = APIRouter()  
  
  
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
    SESSIONS[token] = username.strip()  
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
    if len(username) < 3 or len(password) < 8:  
        raise HTTPException(status_code=400,  
                            detail="Username min 3 chars, password min 8 chars.")  
    try:  
        create_user(username, password)  
    except ValueError as e:  
        raise HTTPException(status_code=400, detail=str(e))  
    logger.info("New user registered: %s", username)  
    return RedirectResponse("/login", status_code=303)  
  
  
@router.post("/logout")  
async def logout(request: Request):  
    token = request.cookies.get("dizer_session")  
    SESSIONS.pop(token or "", None)  
    delete_session(token or "")  
    resp = RedirectResponse("/login", status_code=303)  
    resp.delete_cookie("dizer_session")  
    return resp  
  
  
# ---------------------------------------------------------------------------  
# Routes: app  
# ---------------------------------------------------------------------------  
@router.get("/", response_class=HTMLResponse)  
async def index(request: Request):  
    token = request.cookies.get("dizer_session")  
    if not SESSIONS.get(token or ""):  
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
  
    # Fold uploaded text files into the prompt as context.  
    total = 0  
    for f in files:  
        raw = await f.read()  
        if not raw:  
            continue  
        total += len(raw)  
        if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_FILE_BYTES:  
            raise HTTPException(status_code=400, detail="Uploaded files too large.")  
        try:  
            text = raw.decode("utf-8")  
        except UnicodeDecodeError:  
            # Binary (e.g. image) — note it but don't try to inline it.  
            prompt += f"\n\n[Attached binary file: {f.filename} ({len(raw)} bytes)]"  
            continue  
        prompt += f"\n\n--- FILE: {f.filename} ---\n{text}"  
  
    if len(prompt) > MAX_PROMPT_CHARS:  
        raise HTTPException(status_code=400, detail="Prompt (with files) too large.")  
  
    job = Job(  
        id=uuid.uuid4().hex[:12],  
        owner=user,  
        prompt=prompt,  
        complexity=complexity,  
        stages={"openrouter": openrouter == "on",  
                "groq": groq == "on",  
                "gemini": gemini == "on"},  
    )  
    JOBS[job.id] = job  
    save_job(job)  
    TASKS[job.id] = asyncio.create_task(run_pipeline(job))  
    return JSONResponse({"job_id": job.id})  
  
  
@router.get("/jobs")  
async def jobs(request: Request):  
    user = current_user(request)  
    mine = [j for j in JOBS.values() if j.owner == user]  
    mine.sort(key=lambda j: j.created_at, reverse=True)  
    return JSONResponse([  
        {"id": j.id, "state": j.state, "created_at": j.created_at,  
         "title": (j.prompt[:60] + ("…" if len(j.prompt) > 60 else ""))}  
        for j in mine  
    ])  
  
  
@router.delete("/jobs/{job_id}")  
async def delete_job(job_id: str, request: Request):  
    user = current_user(request)  
    job = JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    # Cancel a running task before removing it.  
    task = TASKS.get(job_id)  
    if task and not task.done():  
        task.cancel()  
    JOBS.pop(job_id, None)  
    TASKS.pop(job_id, None)  
    delete_job_row(job_id)  
    return JSONResponse({"ok": True})  
  
  
@router.get("/status/{job_id}")  
async def status(job_id: str, request: Request):  
    user = current_user(request)  
    job = JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    return JSONResponse({  
        "id": job.id, "state": job.state, "error": job.error,  
        "complexity": job.complexity,  
        "steps": job.steps, "updated_at": job.updated_at,  
    })  
  
  
@router.post("/stop/{job_id}")  
async def stop(job_id: str, request: Request):  
    user = current_user(request)  
    job = JOBS.get(job_id)  
    if not job or job.owner != user:  
        raise HTTPException(status_code=404, detail="Job not found.")  
    task = TASKS.get(job_id)  
    if task and not task.done():  
        task.cancel()  
    return JSONResponse({"ok": True})  
  
  
@router.get("/favicon.ico")  
async def favicon() -> Response:  
    return Response(status_code=204)