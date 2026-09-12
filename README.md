# DizerCoreAI — AI Architect  
  
A self-hosted, multi-agent code pipeline that runs headless on a Raspberry Pi 5.  
You paste a task, pick a complexity (1–5), and three AI stages turn it into  
cleaned, verified code.  
  
## Pipeline  
1. **OpenRouter (free)** reads your raw instruction (+ attached files) and generates the code.  
2. **Groq (Cloud)** verifies that code against your original input, fixes issues, and returns improved code.  
3. **Gemini (Google AI Studio)** returns the final cleaned, optimised and refactored code.  
  
Each stage has its own on/off toggle. If a model hits a paywall/quota, untick it —  
a disabled stage shows a **"skipped"** marker and forwards the previous stage's  
output (stage 1 off = your raw input passes straight to Groq).  
  
### Complexity tiers (you choose, 1–5)  
- **1–2 → light** models (fast, generous daily limits)  
- **3 → normal**  
- **4–5 → heavy** models (highest quality, tighter daily caps)  
  
Each provider rotates through a per-tier list of model slugs; if one returns junk  
or errors, it rotates to the next. The panel shows **which model was used** and a  
**per-stage confidence %**.  
  
### Safety features  
- **Safetywall:** each stage re-checks its own output and retries on junk  
  (`MAX_SAFETYWALL_TRIES`, default 3).  
- **Rate-limit throttle:** a delay before every outbound call  
  (`RATE_LIMIT_DELAY`, default 6s) to avoid free-tier burst 429s.  
  
## Project layout  
```  
config.py        # env loading, path constants, per-tier model tables, throttle knobs  
db.py            # SQLite users/sessions/jobs, State enum, Job dataclass  
providers.py     # OpenRouter/Groq/Gemini calls, rotation, safetywall, confidence  
pipeline.py      # run_pipeline: tier select, 3 stages, skip markers, logging  
auth.py          # user/session helpers, login/register HTML  
routes.py        # FastAPI routes (/run, /jobs, DELETE /jobs/{id}, /status, /stop)  
web.py           # DASHBOARD_HTML (logo, complexity selector, confidence, controls)  
dizercoreai.py   # entrypoint: app, lifespan, StaticFiles mount, uvicorn  
static/  
  dizercore.png  # logo (shown in dashboard + used as favicon)  
install.sh       # one-shot Pi installer  
```  
  
## Install (Raspberry Pi 5)  
One-shot installer (clones the repo, mounts/points at the SSD, prompts for API  
keys, installs a systemd service, prints the URL):  
```bash  
curl -fsSL https://raw.githubusercontent.com/vekzla/DizerCore-AI/main/install.sh | tr -d '\r' | bash  
```  
The installer detects the SSD, mounts it at `/mnt/dizerdata`, prompts for your API  
keys in order (Gemini → OpenRouter → Groq), installs the `dizercore` service, and  
prints the URL using the Pi's detected IP. If it applies the USB UAS quirk, it  
asks you to reboot and re-run once.  
  
## Configuration  
All settings are environment variables (see `.env.example`). The installer writes  
the keys and data dir to `/mnt/dizerdata/dizercore/dizercore.env`. To change models  
or tiers, add the matching `*_MODELS_LIGHT/_NORMAL/_HEAVY` line to that env file and  
restart:  
```bash  
sudo nano /mnt/dizerdata/dizercore/dizercore.env  
sudo systemctl restart dizercore  
```  
  
## Usage  
1. Open `http://<pi-ip>:8000/` and register/log in.  
2. Paste your task, attach files (`.txt .h .cpp .sql`, images), pick complexity 1–5.  
3. Untick any stage you want to skip (e.g. Gemini when you've hit its daily cap).  
4. Click **Run**. Watch each stage populate with its output, model used, and confidence.  
5. **Clear chat** empties the prompt box; the red **×** on a history item deletes it.  
  
> Tip on complexity: if a `3` gives poor code, re-run the same task at `4` or `5` to  
> route it to heavier models.  
  
## Notes / limitations  
- No HTTPS by default (LAN use). Front with nginx/Caddy for TLS.  
- Data (SQLite DBs, uploads) lives on the SSD under `DIZER_DATA_DIR`, keeping the microSD free.  
- Free-tier caps still apply per provider/model/day; when one is exhausted, untick it  
  or bump the tier to a different slug. The safetywall only retries *junk*, not 429s.  
- A wrong/retired model slug is silently skipped and wastes a rotation slot — verify  
  slugs on each provider's models page.  
  
## License  
GNU General Public License v3.0 (GPLv3)