# auth.py  
# DizercoreAI — auth helpers (cookie-session) and auth-page HTML.  
#  
# The user + session STORE (SQLite/PBKDF2) lives in db.py. This module used to  
# carry its own duplicate copies of those functions; that duplication is removed  
# and they are re-exported from db.py so there is a single source of truth and  
# the two can never drift out of sync.  
from fastapi import HTTPException, Request  
  
import runtime  
# Re-export the store functions from db.py (single source of truth). Callers that  
# previously imported these from auth continue to work unchanged.  
from db import (  # noqa: F401  (re-exported for backward compatibility)  
    init_users_db,  
    create_user,  
    verify_user,  
    init_sessions_db,  
    load_sessions,  
    save_session,  
    delete_session,  
)  
  
COOKIE_NAME = "dizer_session"  
  
  
# --------------------------------------------------------------------------- #  
# Auth (cookie-session)  
# --------------------------------------------------------------------------- #  
def current_user(request: Request) -> str:  
    token = request.cookies.get(COOKIE_NAME)  
    user = runtime.SESSIONS.get(token or "")  
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
