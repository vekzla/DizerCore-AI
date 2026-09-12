# auth.py  
# DizercoreAI — user + session store (SQLite, stdlib PBKDF2) and auth helpers.  
import hashlib  
import hmac  
import secrets  
import sqlite3  
import time  
  
from fastapi import HTTPException, Request  
  
from config import USERS_DB, SESSIONS_DB  
  
# In-memory session cache (mirrors the SQLite sessions table for fast lookups).  
SESSIONS: dict[str, str] = {}  
  
COOKIE_NAME = "dizer_session"  
  
  
# --------------------------------------------------------------------------- #  
# User store (SQLite + PBKDF2 salted hashing, stdlib only)  
# --------------------------------------------------------------------------- #  
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
  
  
# --------------------------------------------------------------------------- #  
# Session store (SQLite so logins survive service restarts)  
# --------------------------------------------------------------------------- #  
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
  
  
# --------------------------------------------------------------------------- #  
# Auth (cookie-session)  
# --------------------------------------------------------------------------- #  
def current_user(request: Request) -> str:  
    token = request.cookies.get(COOKIE_NAME)  
    user = SESSIONS.get(token or "")  
    if not user:  
        raise HTTPException(status_code=401, detail="Not authenticated")  
    return user  
  
  
# --------------------------------------------------------------------------- #  
# HTML templates for auth pages  
# --------------------------------------------------------------------------- #  
_STYLE = """  
<style>  
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;  
         background:#0f172a; color:#f8fafc; margin:0; }  
  a { color:#38bdf8; }  
  input, textarea, select { background:#1e293b; color:#f8fafc; border:1px solid #334155;  
         padding:10px; border-radius:6px; font-size:14px; }  
  button { background:#0284c7; color:#fff; border:none; padding:10px 18px;  
         border-radius:6px; font-size:14px; cursor:pointer; }  
  button.stop { background:#b91c1c; }  
  .center { max-width:380px; margin:80px auto; padding:24px; }  
  h2 { color:#38bdf8; }  
</style>  
"""  
  
LOGIN_HTML = f"""<!DOCTYPE html><html><head><title>DizercoreAI Login</title>{_STYLE}</head>  
<body><div class="center"><h2>DizercoreAI</h2>  
<form method="post" action="/login">  
  <p><input name="username" placeholder="Username" style="width:100%"></p>  
  <p><input name="password" type="password" placeholder="Password" style="width:100%"></p>  
  <button type="submit">Log in</button>  
</form>  
<p>No account? <a href="/register">Create one</a></p>  
</div></body></html>"""  
  
REGISTER_HTML = f"""<!DOCTYPE html><html><head><title>DizercoreAI Register</title>{_STYLE}</head>  
<body><div class="center"><h2>Create account</h2>  
<form method="post" action="/register">  
  <p><input name="username" placeholder="Username (min 3)" style="width:100%"></p>  
  <p><input name="password" type="password" placeholder="Password (min 8)" style="width:100%"></p>  
  <button type="submit">Register</button>  
</form>  
<p><a href="/login">Back to login</a></p>  
</div></body></html>"""