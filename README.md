# DizerCoreAI — AI Architect  
  
A self-hosted, multi-agent code pipeline that runs headless on a Raspberry Pi 5.  
You paste a task, pick a complexity (1–5), and three AI agents each write their own  
solution. A pool of judge models then scores every agent's output and picks the best.  
  
## Pipeline  
  
All three agents work **independently and in parallel** none of them checks or  
builds on another's output. Each is given the same task (your raw instruction plus  
any attached files) and writes its own complete solution:  
  
1. **OpenRouter (free)** generates code and judges your request.  
2. **Groq (Cloud)** generates code for your request.  
3. **Gemini (Google AI Studio)** generates code for your request.  
  
Each agent has its own on/off toggle. If a model hits a paywall/quota, untick it,  
a disabled agent shows a **"skipped"** marker and is left out of the judging.  
  
## Judge pool (picks the best output)  
  
After the agents finish, a pool of **judge models** (`JUDGE_MODELS`) scores each  
agent's output from 0–100 against your original request. Candidates are scored  
**strictly in series** one agent is fully judged before the next starts and  
each judge call sleeps `JUDGE_DELAY` (default 5s) first, so the judge key never  
gets a burst that trips its per-minute token limit. For each candidate the  
judges are tried **in order** and the **first usable numeric score wins** a  
judge that errors or returns non-numeric output is discarded and the next slug  
is tried, falling through to `JUDGE_FALLBACK_MODELS` if needed. Each judge  
reply includes a `SCORE:` plus `COMMENTS:` explaining the score, shown under  
the agent's panel. The agent with the **highest score** is reported as the  
best, and the winning judge's comments appear in the summary.  
  
The judges authenticate with `OPENROUTER_API_KEY_JUDGE` a separate OpenRouter  
key used **only** for scoring, so the judge pool can't rate-limit the  
generation key (and vice versa). If unset, it falls back to  
`OPENROUTER_API_KEY_CODER`.  
  
Toggle the pool on/off with the **Judge Pool** checkbox in the dashboard.
  
## Complexity tiers (you choose, 1–5)  
  
- **1–2 → light** models (fast, generous daily limits)  
- **3 → normal**  
- **4–5 → heavy** models (highest quality, tighter daily caps)  
  
Each provider rotates through a per-tier list of model slugs; if one returns junk or  
errors, it rotates to the next. Each panel shows **which model was used** and a  
**per-agent confidence %** (the judge score).  
  
## Safety features  
  
- **Safetywall:** each agent re-checks its own output and retries on junk, rotating  
  through the tier's fallback slugs (`MAX_SAFETYWALL_TRIES`, default 8).  
- **Rate-limit throttle:** a delay before every outbound call (`RATE_LIMIT_DELAY`,  
  default 6s) to avoid free-tier burst 429s.  
- **Groq output cap:** `GROQ_MAX_OUTPUT_TOKENS` (default 3000) because gpt-oss/qwen  
  share an 8K tokens/minute budget across prompt + output.
- **Separate judge key:** `OPENROUTER_API_KEY_JUDGE` gives scoring its own quota.  
- **Serial judge throttle:** judge calls run one at a time with `JUDGE_DELAY`  
  (default 5s) between them, separate from `RATE_LIMIT_DELAY`.
- **Separate coder key:** `OPENROUTER_API_KEY_CODER` undertakes the coding process.
- **Reasoning flag:** every configured slug is called with `reasoning: {enabled: true}`.

## Accounts  
  
- Register on the login page: username min 5 chars, password min 8.  
- **Delete account:** the "Delete an account" link on the login page opens an  
  admin page listing all usernames. Deleting requires the `WEBUI_ADMIN_PASSWORD`  
  set by install.sh it removes the account, all sessions, and all job history.  
  If the env var is unset, the endpoint rejects every attempt (403).
  
## Project layout  
  
| File | Purpose |  
| --- | --- |  
| `config.py` | env loading, paths, per-tier model tables, judges, throttle knobs |  
| `db.py` | SQLite users/sessions/jobs, State enum, Job dataclass |  
| `providers.py` | OpenRouter/Groq/Gemini calls, rotation, safetywall, judge confidence |  
| `pipeline.py` | run_pipeline: tier select, 3 parallel agents, parallel judging, winner |  
| `auth.py` | cookie-session auth + login/register/delete-account HTML |  
| `routes.py` | FastAPI routes (/run, /jobs, /status, /stop, /delete-account) |
| `web.py` | DASHBOARD_HTML |  
| `dizercoreai.py` | entrypoint: app, lifespan, StaticFiles, uvicorn |  
| `static/dizercore.png` | logo / favicon |  
| `install.sh` | one-shot Pi installer (SSD detect/format/mount + hotfix) |  
  
## Install (Raspberry Pi 5)  
  
```bash  

curl -fsSL https://raw.githubusercontent.com/vekzla/DizerCore-AI/main/install.sh | tr -d '\r' | bash

```

The installer auto-detects plugged-in SSDs (excluding the boot disk), lets you pick
the target, applies the UAS quirk hotfix automatically (reboot once, re-run), formats
to ext4 only if needed (with an erase warning), mounts by UUID at /mnt/dizerdata,
prompts for API keys (including an optional dedicated OpenRouter judge key and  
the web UI admin password), installs the dizercore service, and prints the URL.

## Configuration

Env file: /mnt/dizerdata/dizercore/dizercore.env edit, 
then sudo systemctl restart dizercore. Keys: OPENROUTER_API_KEY_CODER (required),  
OPENROUTER_API_KEY_JUDGE (optional judge quota), WEBUI_ADMIN_PASSWORD (delete-account gate). 
Override tiers with OPENROUTER_MODEL_LIGHT|NORMAL|HEAVY (comma-separated slugs); 
judges with JUDGE_MODELS / JUDGE_FALLBACK_MODELS.  
Throttles: RATE_LIMIT_DELAY (generation, 6s), JUDGE_DELAY (judges, 5s).

## Usage

    Open http://<pi-ip>:8000/, register/log in.
    Paste your task, attach files, pick complexity 1–5, untick agents to skip.
    Run each panel shows output, model used, and judge confidence.

## Notes / limitations

    No HTTPS by default (LAN use). Front with nginx/Caddy for TLS.
    Without OPENROUTER_API_KEY_JUDGE, judges share the coder key's quota. 
    Judging is intentionally serial & delayed worst case it walks the whole judge pool
    per candiate before falling back.
    Free-tier caps still apply; wrong/retired slugs are skipped after a wasted call.
    Attached images are noted as placeholders, not analysed as vision input.

## License
GNU General Public License v3.0 (GPLv3)
