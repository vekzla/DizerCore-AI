# version.py  
# DizercoreAI — reports which version the Pi is running.  
# install.sh writes a short git SHA into a VERSION file at install time;  
# this reads it, falling back to a live git call, then to "unknown".  
import os  
import subprocess  
  
_HERE = os.path.dirname(os.path.abspath(__file__))  
_VERSION_FILE = os.path.join(_HERE, "VERSION")  
  
  
def get_version() -> str:  
    # Prefer the VERSION file written at install time (survives without .git).  
    try:  
        with open(_VERSION_FILE, "r", encoding="utf-8") as f:  
            v = f.read().strip()  
            if v:  
                return v  
    except OSError:  
        pass  
    # Fall back to a live git call if the file is missing.  
    try:  
        out = subprocess.check_output(  
            ["git", "-C", _HERE, "rev-parse", "--short", "HEAD"],  
            stderr=subprocess.DEVNULL,  
        ).decode().strip()  
        return out or "unknown"  
    except Exception:                                # noqa: BLE001  
        return "unknown"