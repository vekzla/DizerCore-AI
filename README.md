# DizerCoreAI - AI Architect  
  
A self-hosted, multi-agent code pipeline that runs headless on a Raspberry Pi 5.  
You write out a task, pick a complexity (1–5), and three AI agents each write their own  
solution. A pool of judge models then scores every agent's output and picks the best.  
  
## Pipeline  
  
All three agents work **independently and in parallel**  none of them checks or  
builds on another's output. Each is given the same task (your raw instruction plus  
any attached files) and writes its own complete solution:  
  
1. **OpenRouter (free)**  tiered coder models.  
2. **Groq (Cloud)**  text-only coder.  
3. **Gemini (Google AI Studio)**  natively multimodal coder.  
  
Each agent has its own on/off toggle. A disabled agent shows a **"skipped"**  
marker and is left out of the judging.  
  
## Live streaming  
  
All agents stream output **token-by-token** into their dashboard panels over a  
server-sent-events endpoint (`/status/stream/{job_id}`). Reasoning-capable  
models (`REASONING_MODELS` in `providers.py`) also stream their "thinking" into  
an italic sub-block under each box, via OpenRouter `reasoning_details` and  
Gemini `thought` parts.  
  
## File attachments & vision routing  
  
Uploads are classified by extension (`classify_upload` in `config.py`):  
  
- **Text/code** (`.txt .md .sql .cpp .h .py .json` …)  decoded and appended to  
  the prompt for every agent.  
- **`.docx`**  text extracted via stdlib zip/XML parsing, appended as text.  
- **Images / PDF**  raw bytes go only to vision-capable models  
  (`VISION_MODELS`: Gemma 4 slugs + all Gemini models). Groq receives a  
  `[Attached file: name (kind)  binary content omitted]` note instead.  
  
## Judge pool (picks the best output)  
  
Judging starts **the moment each agent finishes**  not after all three. Judge  
calls are serialized per job through an `asyncio.Lock` with `JUDGE_DELAY`  
(default 5s) spacing, so the dedicated judge key never sees parallel requests.  
  
Each candidate starts at a **rotated index** into `JUDGE_MODELS` (OpenRouter→0,  
Gemini→1, Groq→last) and wraps through the pool until a usable `SCORE:` lands;  
a judge that errors or returns non-numeric output is discarded. The highest  
score wins the summary, which then gets a **confirmation pass** from  
`JUDGE_MODELS[0]` (the best judge).  
  
Judges authenticate with `OPENROUTER_API_KEY_JUDGE`  a separate OpenRouter key  
used **only** for scoring. If unset, it falls back to `OPENROUTER_API_KEY_CODER`.  
Toggle the pool with the **Judge Pool** checkbox.  
  
## Complexity tiers (you choose, 1–5)  
  
- **1–2 → light**  `poolside/laguna-xs-2.1`, `cohere/north-mini-code`, `thinkingmachines/inkling-small`  
- **3 → normal**  `poolside/laguna-s-2.1`, `thinkingmachines/inkling`, `qwen/qwen3.8-27b`  
- **4–5 → heavy**  `nvidia/nemotron-3-super-120b`, `nvidia/nemotron-3-ultra-550b`, `google/gemma-4-31b`  
  
Judges: `google/gemma-4-26b-a4b-it`, `dots-studio/dots-3-note-preview`,  
`liquid/lfm-2.5-2.6b` (all `:free`).  
  
Each provider rotates through its tier's slugs; junk/errors rotate to the next.  
Panels show which model was used, live thinking, and the judge score/comments.  
  
## Safety features  
  
- **Safetywall:** each agent re-checks its own output and retries on junk  
  (`MAX_SAFETYWALL_TRIES`, default 8).  
- **Rate-limit throttle:** `RATE_LIMIT_DELAY` (default 6s) before every  
  generation call.  
- **Groq output cap:** `GROQ_MAX_OUTPUT_TOKENS` (default 3000).  
- **Separate judge key:** `OPENROUTER_API_KEY_JUDGE` gives scoring its own quota.  
- **Serial judge lock:** one judge call at a time per job, `JUDGE_DELAY` apart.  
- **Reasoning flag:** every configured slug gets `reasoning: {enabled: true}`;  
  judges get a 2048-token cap so reasoning can't truncate `SCORE:`.  
  
## Accounts  
  
- Register on the login page: username min 5 chars, password min 8.  
- **Delete account:** admin page gated by `WEBUI_ADMIN_PASSWORD`; removes the  
  account, sessions, and job history. Unset → endpoint always 403s.  
  
## Version / update check  
  
The footer shows `v<sha> (<install timestamp>)`. `install.sh` stamps  
`sha timestamp repo` into a `VERSION` file; at runtime the app asks GitHub for  
the remote `HEAD` once and shows **"update available"** when it differs.  
Falls back to a live `git rev-parse` if `VERSION` is missing.  
  
## Project layout  
  
| File | Purpose |  
| --- | --- |  
| `config.py` | env loading, tier/judge tables, `VISION_MODELS`, `classify_upload`, throttles |  
| `db.py` | SQLite users/sessions/jobs, Job dataclass (incl. attachments metadata) |  
| `providers.py` | streaming provider calls, rotation, safetywall, judge confidence, `REASONING_MODELS` |  
| `pipeline.py` | 3 parallel agents, per-agent judge-on-completion, rotation, winner pick |  
| `runtime.py` | shared state: `JOBS`, `TASKS`, `SESSIONS`, `ATTACH` (upload bytes) |  
| `auth.py` | cookie-session auth + login/register/delete-account HTML |  
| `routes.py` | FastAPI routes incl. `/run` file classification and `/status/stream` SSE |  
| `web.py` | DASHBOARD_HTML (EventSource streaming, thinking blocks) |  
| `dizercoreai.py` | entrypoint: app, lifespan, StaticFiles, uvicorn |  
| `version.py` | build identity + remote update check |  
| `install.sh` | one-shot Pi installer (SSD detect/format/mount + hotfix) |  
  
## Install (Raspberry Pi 5)  
  
```bash  

curl -fsSL "https://raw.githubusercontent.com/vekzla/DizerCore-AI/main/install.sh?nocache=$(date +%s)" | tr -d '\r' | bash

```
Auto-detects SSDs, applies the UAS quirk hotfix (reboot once, re-run), formats
ext4 only if needed, mounts by UUID at /mnt/dizerdata, prompts for API keys
(optional dedicated judge key + admin password), installs the service, prints
the URL.

## Configuration

Env file: /mnt/dizerdata/dizercore/dizercore.env  edit, then
sudo systemctl restart dizercore.
Keys: OPENROUTER_API_KEY_CODER (required), OPENROUTER_API_KEY_JUDGE
(optional), WEBUI_ADMIN_PASSWORD, GEMINI_API_KEY, GROQ_API_KEY.
Override tiers with OPENROUTER_MODEL_LIGHT|NORMAL|HEAVY; judges with
JUDGE_MODELS / JUDGE_FALLBACK_MODELS.
Throttles: RATE_LIMIT_DELAY (6s), JUDGE_DELAY (5s).

## Usage

    Open http://<pi-ip>:8000/, register/log in.
    Type out your task, attach files (images/PDF route to vision agents), pick
    complexity 1–5, untick agents to skip.
    Press Run to start the Agents, Stop to Stop the Agents and Clear to wipe the window clean.
    Job history can be deleted by clicking on 'x'
    Watch each panel stream thinking + code live; judge scores land per agent as
    it finishes; the summary shows the winner plus a confirmation score with the jobs history
    showing "running in orange, done in green and cancelled in grey"

## Notes / limitations

    No HTTPS by default (LAN use). Front with nginx/Caddy for TLS.
    Without OPENROUTER_API_KEY_JUDGE, judges share the coder key's quota.
    Judge calls stay serial & delayed; worst case a candidate walks the whole pool.
    Free-tier caps still apply; wrong/retired slugs are skipped after a wasted call.
    Text-only agents receive a placeholder note for binary uploads  only
    VISION_MODELS see the actual bytes.

## License

GNU General Public License v3.0 (GPLv3)

