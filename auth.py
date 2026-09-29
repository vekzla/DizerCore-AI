# DizerCore-AI  
# ----------------------------------------------------------------------------  
# auth.py — auth helpers (cookie-session) and auth-page HTML.  
#  
# The user + session STORE (SQLite/PBKDF2) lives in db.py. This module re-exports  
# those functions from db.py so there is a single source of truth and the two  
# can never drift out of sync.  
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
    list_users,  
)  
  
COOKIE_NAME = "dizer_session"  
  
  
# --------------------------------------------------------------------------- #  
# Auth (cookie-session)  
# --------------------------------------------------------------------------- #  
def current_user(request: Request) -> str:  
    token = request.cookies.get(COOKIE_NAME)  
    return runtime.SESSIONS.get(token or "", "")  
  
# --------------------------------------------------------------------------- #  
# HTML templates for auth pages  
# --------------------------------------------------------------------------- #  
_STYLE = """  
<style>  
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;  
         background:#0f172a; color:#f8fafc; margin:0; }  
  a { color:#38bdf8; }  
  input, textarea, select { background:#1e293b; color:#f8fafc; border:1px solid #334155;  
         padding:10px; border-radius:6px; font-size:14px; width:100%;  
         box-sizing:border-box; }  
  button { background:#0284c7; color:#fff; border:none; padding:10px 18px;  
         border-radius:6px; font-size:14px; cursor:pointer; }  
  button.stop { background:#b91c1c; }  
  .center { max-width:380px; margin:80px auto; padding:24px; }  
  h2 { color:#38bdf8; }  
  .logo { display:block; margin:0 auto 16px; max-width:120px; height:auto; }  
  .hint { color:#94a3b8; font-size:12px; display:block; margin-top:4px; }  
</style>  
"""  
  
LOGIN_HTML = f"""<!DOCTYPE html><html><head><title>DizerCore-AI Login</title>{_STYLE}</head>  
<body><div class="center">  
<img class="logo" src="/static/dizercore.png" alt="DizerCore-AI logo">  
<h2>DizerCore-AI</h2>  
<form method="post" action="/login">  
  <p><input name="username" placeholder="Username"></p>  
  <p><input name="password" type="password" placeholder="Password"></p>  
  <button type="submit">Log in</button>  
</form>  
<p>No account? <a href="/register">Create one</a></p>  
<p><a href="/delete-account">Delete an account</a></p>  
</div></body></html>"""  
  
REGISTER_HTML = f"""<!DOCTYPE html><html><head><title>DizerCore-AI Register</title>{_STYLE}</head>  
<body><div class="center">  
<img class="logo" src="/static/dizercore.png" alt="DizerCore-AI logo">  
<h2>Create account</h2>  
<form method="post" action="/register">  
  <p><input name="username" placeholder="Username">  
     <span class="hint">Username must be at least 5 characters.</span></p>  
  <p><input name="password" type="password" placeholder="Password">  
     <span class="hint">Password must be at least 8 characters.</span></p>  
  <button type="submit">Register</button>  
</form>  
<p><a href="/login">Back to login</a></p>  
</div></body></html>"""  
  
  
def delete_account_html() -> str:  
    """Render the admin-gated account-deletion page. Rebuilt per request so the  
    username dropdown always reflects the live users table."""  
    options = "".join(  
        f'<option value="{u}">{u}</option>' for u in list_users()  
    ) or "<option value=''>(no users)</option>"  
    return f"""<!DOCTYPE html><html><head><title>DizerCore-AI Delete Account</title>{_STYLE}</head>  
<body><div class="center">  
<img class="logo" src="/static/dizercore.png" alt="DizerCore-AI logo">  
<h2>Delete account</h2>  
<form method="post" action="/delete-account"  
      onsubmit="return confirm('Permanently delete this account, its sessions, and all its jobs?');">  
  <p><select name="username">{options}</select></p>  
  <p><input name="admin_password" type="password" placeholder="Admin password">  
     <span class="hint">The admin password set during install is required.</span></p>  
  <button type="submit" class="stop">Delete account</button>  
</form>  
<p><a href="/login">Back to login</a></p>  
</div></body></html>"""
