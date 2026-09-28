# DizerCore-AI  
# ----------------------------------------------------------------------------  
# version.py — reports which build the Pi is running and where it came from.  
# install.sh stamps "sha timestamp repo" into a VERSION file at install time;  
# this reads it, falls back to a live git call, then to "unknown".  
# check_remote() asks GitHub for the current HEAD once per process (cached),  
# so the dashboard can show "update available" without tracking anything.  
import os  
import subprocess  
  
_HERE = os.path.dirname(os.path.abspath(__file__))  
_VERSION_FILE = os.path.join(_HERE, "VERSION")  
_GITHUB_API = "https://api.github.com/repos/vekzla/DizerCore-AI/commits/main"  
  
_remote_head = None   # cached remote sha once fetched  
  
  
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
  
  
def get_version() -> str:  
    info = _read_version_file()  
    if info:  
        return info["sha"]  
    try:  
        out = subprocess.check_output(  
            ["git", "-C", _HERE, "rev-parse", "--short", "HEAD"],  
            stderr=subprocess.DEVNULL,  
        ).decode().strip()  
        return out or "unknown"  
    except Exception:                                # noqa: BLE001  
        return "unknown"  
  
  
def get_info() -> dict:  
    """Full build identity: sha, install timestamp, source repo."""  
    info = _read_version_file() or {}  
    return {  
        "sha": info.get("sha") or get_version(),  
        "installed_at": info.get("installed_at", ""),  
        "repo": info.get("repo", ""),  
    }  
  
  
async def check_remote() -> str:  
    """Fetch the remote HEAD sha once; '' if offline/unknown. Cached."""  
    global _remote_head  
    if _remote_head is not None:  
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
    return _remote_head
