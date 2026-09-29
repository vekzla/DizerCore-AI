# DizerCore-AI  
# ----------------------------------------------------------------------------  
# version.py — reports which build the Pi is running and where it came from.  
# install.sh stamps "sha timestamp repo" into a VERSION file at install time.  
# The live `git rev-parse` result wins so `git pull` is reflected immediately;  
# the VERSION file only supplies install timestamp / repo metadata.  
# check_remote() asks GitHub for the current HEAD and caches it for 5 minutes,  
# so the dashboard can show "update available" without hammering the API.  
import os  
import subprocess  
import time  
  
_HERE = os.path.dirname(os.path.abspath(__file__))  
_VERSION_FILE = os.path.join(_HERE, "VERSION")  
_GITHUB_API = "https://api.github.com/repos/vekzla/DizerCore-AI/commits/main"  
  
_REMOTE_TTL = 300.0        # seconds between remote HEAD checks  
_remote_head = None        # cached remote sha  
_remote_fetched = 0.0      # epoch of last fetch attempt  
  
  
def _read_version_file():  
    try:  
        with open(_VERSION_FILE, "r", encoding="utf-8") as f:  
            parts = f.read().split()  
            if parts:  
                return {  
                    "sha": parts[0],  
                    "installed_at": parts[1] if len(parts) > 1 else "",  
                    "repo": parts[2] if len(parts) > 2 else "",  
                }  
    except OSError:  
        pass  
    return None  
  
  
def _git_head() -> str:  
    try:  
        out = subprocess.check_output(  
            ["git", "-C", _HERE, "rev-parse", "--short", "HEAD"],  
            stderr=subprocess.DEVNULL,  
        ).decode().strip()  
        return out or "unknown"  
    except Exception:                                # noqa: BLE001  
        return "unknown"  
  
  
def get_version() -> str:  
    return _git_head()  
  
  
def get_info() -> dict:  
    """Full build identity: sha, install timestamp, source repo."""  
    info = _read_version_file() or {}  
    return {  
        "sha": _git_head(),  
        "installed_at": info.get("installed_at", ""),  
        "repo": info.get("repo", ""),  
    }  
  
  
async def check_remote() -> str:  
    """Fetch the remote HEAD sha; cached for _REMOTE_TTL seconds."""  
    global _remote_head, _remote_fetched  
    if _remote_head is not None and (time.time() - _remote_fetched) < _REMOTE_TTL:  
        return _remote_head  
    try:  
        import runtime  
        r = await runtime.http_client.get(  
            _GITHUB_API, timeout=10.0,  
            headers={"Accept": "application/vnd.github.sha"},  
        )  
        _remote_head = r.text.strip()[:7] if r.status_code == 200 else ""  
    except Exception:                                # noqa: BLE001  
        _remote_head = ""  
    _remote_fetched = time.time()  
    return _remote_head
