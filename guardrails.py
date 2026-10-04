# DizerCore-AI  
# ----------------------------------------------------------------------------  
# guardrails.py — output sanitization between agents/judges and the build.  
# HARD RULE: only fenced code blocks leave this module. Prose, explanations,  
# "here's your code" waffle, and summary text never reach the build payload.  
# A judge comment appended to job.steps["summary"] (see pipeline._pick_winner)  
# can NEVER leak downstream because we never read summary only raw agent  
# output through extract_code().  
import re  
  
_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.-]*)(?::([^\n`]+))?\n(.*?)```", re.S)  
  
# Fence languages that are prose, not code — dropped unconditionally.  
_NONCODE_LANGS = {"text", "txt", "markdown", "md", "json", "yaml", "yml",  
                  "csv", "log", "output", "console"}  
  
_CODE_TOKENS = re.compile(r"[=(){};#<>/*\\]|^import |^from |^#include|"  
                          r"^\s*(def |class |fn |func |int |void |return\b)")  
  
# A line that looks like a plain-English sentence: word chars, ends in  
# terminal punctuation, contains none of the code tokens above.  
_PROSE_RE = re.compile(r"^[A-Z][A-Za-z0-9 ',\-]{10,}[.!?]$")  
  
  
def _looks_prose(line: str) -> bool:  
    s = line.strip()  
    if not s:  
        return False  
    if _CODE_TOKENS.search(s):  
        return False  
    if s.startswith(("//", "#", "/*", "*", "<!--")):  
        return False                     # legit code comments — keep them  
    return bool(_PROSE_RE.match(s))  
  
  
def _block_is_prose(body: str) -> bool:  
    """True if >60% of non-empty lines look like sentences, not code."""  
    lines = [l for l in body.splitlines() if l.strip()]  
    if not lines:  
        return True  
    prose = sum(1 for l in lines if _looks_prose(l))  
    return prose / len(lines) > 0.6  
  
  
def extract_code(text: str) -> list[tuple[str, str, str]]:  
    """Pull fenced blocks out of agent output.  
    Returns [(lang, path_hint, body), ...] — prose outside fences is gone by  
    construction; prose-looking and non-code-language blocks are dropped."""  
    out = []  
    for lang, hint, body in _FENCE_RE.findall(text or ""):  
        lang = (lang or "").lower().strip()  
        if lang in _NONCODE_LANGS:  
            continue  
        body = "\n".join(                 # strip stray nested fence lines  
            l for l in body.splitlines() if not l.strip().startswith("```"))  
        if not body.strip() or _block_is_prose(body):  
            continue  
        out.append((lang, (hint or "").strip(), body))  
    return out  
  
  
def _safe_relpath(hint: str) -> str | None:  
    """Reject absolute paths and anything escaping the workspace."""  
    if not hint:  
        return None  
    hint = hint.lstrip("/")  
    if not hint or hint.startswith("..") or "/../" in f"/{hint}/" \  
            or "\\" in hint:  
        return None  
    return hint  
  
  
def build_package(text: str) -> dict | None:  
    """Turn raw agent output into a clean, buildable package.  
    Returns {"files": {relpath: code}, "primary": (lang, code)} or None when  
    no usable code exists — callers must NOT push anything to a builder then."""  
    blocks = extract_code(text)  
    if not blocks:  
        return None  
  
    files, primary = {}, None  
    fallback_names = {  
        "python": "main.py", "py": "main.py",  
        "c": "main.c", "cpp": "main.cpp", "c++": "main.cpp",  
        "bash": "main.sh", "sh": "main.sh",  
        "diff": "changes.diff",  
    }  
    for i, (lang, hint, body) in enumerate(blocks):  
        rel = _safe_relpath(hint) or fallback_names.get(  
            lang, f"snippet_{i}.{lang or 'txt'}")  
        if lang == "diff":  
            files.setdefault("changes.diff", body)  
            continue  
        files[rel] = body  
        if primary is None:  
            primary = (lang, body)  
    return {"files": files, "primary": primary} if files else None
