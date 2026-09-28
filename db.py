# DizerCore-AI  
# ----------------------------------------------------------------------------  
# db.py — SQLite persistence for DizerCoreAI: users, sessions, and jobs.  
# Pure stdlib (sqlite3 + hashlib/hmac) — no external DB dependency.  
import hashlib  
import hmac  
import json  
import secrets  
import time  
from dataclasses import dataclass, field, asdict  
from enum import Enum  
  
from config import USERS_DB, SESSIONS_DB, JOBS_DB  
import sqlite3  
  
  
# ---------------------------------------------------------------------------  
# User store (SQLite + PBKDF2 salted hashing, stdlib only)  
# ---------------------------------------------------------------------------  
def init_users_db() -> None:  
    with sqlite3.connect(USERS_DB) as c:  
        c.execute("""CREATE TABLE IF NOT EXISTS users (  
            username TEXT PRIMARY KEY,  
            salt TEXT NOT NULL,  
            pwhash TEXT NOT NULL,  
            created_at REAL NOT NULL)""")  
  
  
def _hash_pw(password: str, salt: bytes) -> str:  
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()  
  
  
def create_user(username: str, password: str) -> None:  
    salt = secrets.token_bytes(16)  
    pwhash = _hash_pw(password, salt)  
    try:  
        with sqlite3.connect(USERS_DB) as c:  
            c.execute("INSERT INTO users VALUES (?,?,?,?)",  
                      (username, salt.hex(), pwhash, time.time()))  
    except sqlite3.IntegrityError:  
        raise ValueError("Username already exists.")  
  
  
def verify_user(username: str, password: str) -> bool:  
    with sqlite3.connect(USERS_DB) as c:  
        row = c.execute("SELECT salt, pwhash FROM users WHERE username=?",  
                        (username,)).fetchone()  
    if not row:  
        return False  
    salt_hex, pwhash = row  
    candidate = _hash_pw(password, bytes.fromhex(salt_hex))  
    return hmac.compare_digest(candidate, pwhash)  
  
  
def list_users() -> list:  
    """All registered usernames, alphabetical — feeds the delete-account dropdown."""  
    with sqlite3.connect(USERS_DB) as c:  
        return [r[0] for r in c.execute(  
            "SELECT username FROM users ORDER BY username").fetchall()]  
  
  
def delete_user(username: str) -> None:  
    with sqlite3.connect(USERS_DB) as c:  
        c.execute("DELETE FROM users WHERE username=?", (username,))  
  
  
# ---------------------------------------------------------------------------  
# Session store (SQLite so logins survive service restarts)  
# ---------------------------------------------------------------------------  
def init_sessions_db() -> None:  
    with sqlite3.connect(SESSIONS_DB) as c:  
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (  
            token TEXT PRIMARY KEY,  
            username TEXT NOT NULL,  
            created_at REAL NOT NULL)""")  
  
  
def load_sessions() -> dict:  
    out: dict = {}  
    with sqlite3.connect(SESSIONS_DB) as c:  
        for token, username in c.execute("SELECT token, username FROM sessions"):  
            out[token] = username  
    return out  
  
  
def save_session(token: str, username: str) -> None:  
    with sqlite3.connect(SESSIONS_DB) as c:  
        c.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)",  
                  (token, username, time.time()))  
  
  
def delete_session(token: str) -> None:  
    with sqlite3.connect(SESSIONS_DB) as c:  
        c.execute("DELETE FROM sessions WHERE token=?", (token,))  
  
  
def delete_user_sessions(username: str) -> None:  
    """Delete every session belonging to a user — used by account deletion."""  
    with sqlite3.connect(SESSIONS_DB) as c:  
        c.execute("DELETE FROM sessions WHERE username=?", (username,))  
  
  
# ---------------------------------------------------------------------------  
# Job store (SQLite persistence so history survives restarts)  
# ---------------------------------------------------------------------------  
class State(str, Enum):  
    QUEUED = "queued"  
    RUNNING = "running"  
    DONE = "done"  
    FAILED = "failed"  
    CANCELLED = "cancelled"  
  
  
def _default_steps() -> dict:  
    # Per stage we keep the text output plus which model produced it, a  
    # 0-100 confidence score (scored by the judge pool, not the stage's own  
    # model), and the judge's detailed comments explaining that score.  
    # Blank strings render as empty panels in the UI.  
    # `*_status` is a live progress flag ("working"/"done"/"") that the  
    # dashboard animates into a "working…" spinner while the stage runs.  
    # `*_thinking` holds the model's reasoning/thinking tokens, streamed  
    # live into a gray sub-block in the UI while the stage runs.  
    # `summary` / `summary_conf` hold the judge pool's "best is X (NN%)" line  
    # plus the winning judge's comments.  
    return {  
        "generate": "", "generate_model": "", "generate_conf": "",  
        "generate_status": "", "generate_judge_comments": "",  
        "generate_thinking": "",  
        "verify": "",   "verify_model": "",   "verify_conf": "",  
        "verify_status": "",   "verify_judge_comments": "",  
        "verify_thinking": "",  
        "final": "",    "final_model": "",    "final_conf": "",  
        "final_status": "",    "final_judge_comments": "",  
        "final_thinking": "",  
        "summary": "",  "summary_conf": "",   "summary_status": "",  
    }  
  
  
def _default_stages() -> dict:  
    # openrouter/groq/gemini are the three generator stages; inkling is the  
    # judge pool (checked on by default in the dashboard).  
    return {"openrouter": True, "groq": True, "gemini": True, "inkling": True}  
  
  
@dataclass  
class Job:  
    id: str  
    owner: str  
    prompt: str  
    complexity: int = 3          # 1-2 light, 3 normal, 4-5 heavy (user-set)  
    state: str = State.QUEUED  
    error: str = ""  
    steps: dict = field(default_factory=_default_steps)  
    stages: dict = field(default_factory=_default_stages)  
    # Metadata ONLY for uploaded files: [{"name": ..., "kind": "image|pdf|text",  
    # "mime": ...}]. NEVER store raw bytes here — save_job() json.dumps()s the  
    # whole dataclass and bytes are not JSON-serializable. Raw bytes live in  
    # runtime.ATTACH[job_id] for the lifetime of the process.  
    attachments: list = field(default_factory=list)  
    created_at: float = field(default_factory=time.time)  
    updated_at: float = field(default_factory=time.time)  
  
    def touch(self) -> None:  
        self.updated_at = time.time()  
  
  
def init_jobs_db() -> None:  
    with sqlite3.connect(JOBS_DB) as c:  
        c.execute("""CREATE TABLE IF NOT EXISTS jobs (  
            id TEXT PRIMARY KEY,  
            owner TEXT NOT NULL,  
            data TEXT NOT NULL,  
            updated_at REAL NOT NULL)""")  
  
  
def save_job(job: Job) -> None:  
    with sqlite3.connect(JOBS_DB) as c:  
        c.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)",  
                  (job.id, job.owner, json.dumps(asdict(job)), job.updated_at))  
  
  
def delete_job_row(job_id: str) -> None:  
    with sqlite3.connect(JOBS_DB) as c:  
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))  
  
  
def delete_user_jobs(username: str) -> None:  
    """Delete every job owned by a user — used by account deletion."""  
    with sqlite3.connect(JOBS_DB) as c:  
        c.execute("DELETE FROM jobs WHERE owner=?", (username,))  
  
  
def load_jobs() -> dict:  
    out: dict = {}  
    with sqlite3.connect(JOBS_DB) as c:  
        for jid, data in c.execute("SELECT id, data FROM jobs"):  
            d = json.loads(data)  
            # Any job still marked running at load time crashed with the server.  
            if d.get("state") == State.RUNNING:  
                d["state"] = State.FAILED  
                d["error"] = "Server restarted while job was running."  
            # Backfill new fields for jobs saved by an older version.  
            d.setdefault("complexity", 3)  
            d.setdefault("attachments", [])  
            merged_steps = _default_steps()  
            merged_steps.update(d.get("steps", {}))  
            d["steps"] = merged_steps  
            merged_stages = _default_stages()  
            merged_stages.update(d.get("stages", {}))  
            d["stages"] = merged_stages  
            out[jid] = Job(**d)  
    return out
