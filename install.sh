#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install.sh — one-shot installer for Raspberry Pi 5 (headless).  
#  
# FIRST asks which role this machine plays:  
#   [1] DizerCore-AI.Code-Agent  — the main pipeline pi (this script's  
#        full install: SSD wipe/mount, repo, venv, keys, service).  
#   [2] DizerCore-AI.Build-Agent — the remote build executor pi.  
#        Downloads install-executor.sh to a real file and runs it.  
#  
# Code-Agent path:  
#   Auto-detects plugged-in SSDs (excludes the SD card / boot disk),  
#   lets the user pick the target, applies the UAS quirk hotfix  
#   automatically, then ALWAYS wipes the picked disk clean (new GPT  
#   label + single ext4 partition) after a typed ERASE confirmation.  
#   Mounts by UUID at /mnt/dizerdata, writes the env file (OpenAI  
#   coder key + Groq + Gemini + required OpenRouter JUDGE key),  
#   optionally configures the Build-Agent executor by IP (SSH keygen +  
#   smoke test -> BUILD_* env vars), installs the systemd service.  
#  
# KEY BACKUP: the env file (API keys + admin password) is backed up to  
# ~/dizercore.env.bak on the SD card, so reinstalls can restore keys  
# even though the SSD is fully wiped.  
#  
# BOTH pis take the other pi's IP address — no hostnames needed.  
# ==================================================================  
set -Eeuo pipefail  
  
REPO="https://github.com/vekzla/DizerCore-AI.git"  
BRANCH="main"  
APP_NAME="DizerCoreAI"  
ENTRYPOINT="dizercoreai.py"  
SERVICE_NAME="dizercore"  
PORT="8000"  
  
SSD_LABEL="DizerCore"  
DATA_MOUNT="/mnt/dizerdata"  
DATA_DIR="${DATA_MOUNT}/dizercore"  
ENV_FILE="${DATA_DIR}/dizercore.env"  
ENV_BAK="${HOME}/dizercore.env.bak"   # SD card — survives SSD wipes  
  
APP_DIR="${HOME}/DizerCore-AI"  
SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"  
USER_NAME="$(whoami)"  
  
QUIRK="usb-storage.quirks=152d:0578:u"  
CMDLINE="/boot/firmware/cmdline.txt"  
  
# SSH user on the Build-Agent — must match BUILD_USER in  
# install-executor.sh exactly or every ssh/rsync call fails.  
BUILD_SSH_USER="dizercorebuild"  
  
# Executor installer fetched when role = Build-Agent.  
EXECUTOR_URL="https://raw.githubusercontent.com/vekzla/DizerCore-AI/main/install-executor.sh"  
  
# Every variable Config.from_env() requires — used by the stale-backup  
# guard and the fresh-write block. Keep in sync with config.py.  
REQUIRED_KEYS=(GEMINI_API_KEY OPENAI_API_KEY GROQ_API_KEY OPENROUTER_API_KEY_JUDGE)  
  
banner() { echo "============================================================"; echo " $1"; echo "============================================================"; }  
ok()   { echo "==> $1"; }  
warn() { echo "!!  $1" >&2; }  
die()  { echo "XX  $1" >&2; exit 1; }  
  
confirm() {  
  local reply=""  
  read -r -p "$1 [y/N] " reply </dev/tty || true  
  [[ "$reply" =~ ^[Yy]$ ]]  
}  
  
require_tty() { [ -e /dev/tty ] || die "No TTY available; run in an interactive shell."; }  
  
# ask_ip <prompt> -> sets REPLY_IP to a validated IPv4 string.  
# Optional $2 is a pre-filled default (shown in [brackets]).  
ask_ip() {  
  local prompt="$1" guess="${2:-}" val=""  
  while true; do  
    if [ -n "$guess" ]; then  
      read -r -p "${prompt} [${guess}]: " val </dev/tty || true  
      val="${val:-$guess}"  
    else  
      read -r -p "${prompt}: " val </dev/tty || true  
    fi  
    val="$(echo "$val" | tr -d '[:space:]')"  
    if [[ "$val" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then  
      REPLY_IP="$val"; return 0  
    fi  
    warn "Enter an IPv4 address like 192.168.1.50"  
  done  
}  
  
# set_env KEY VALUE — rewrite KEY=VALUE in $ENV_FILE, or append if absent.  
# Always produces exactly one line for the key.  
set_env() {  
  local key="$1" val="$2"  
  if grep -q "^${key}=" "$ENV_FILE"; then  
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"  
  else  
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"  
  fi  
}  
  
# ------------------------------------------------------------------  
# pick_ssd — scan block devices, exclude the boot disk, let the user  
# choose. Sets SSD_DEV (a partition) and SSD_DISK (its parent disk).  
# The picked disk is ALWAYS wiped; nothing is kept.  
# ------------------------------------------------------------------  
pick_ssd() {  
  local root_src root_disk  
  root_src="$(findmnt -n -o SOURCE / 2>/dev/null || true)"  
  root_disk="$(basename "$(lsblk -n -o PKNAME "$root_src" 2>/dev/null || true)")"  
  [ -z "$root_disk" ] && root_disk="$(basename "$root_src" | sed 's/p*[0-9]*$//')"  
  
  mapfile -t ROWS < <(lsblk -lnpo NAME,TYPE,FSTYPE,SIZE,PKNAME,MOUNTPOINT 2>/dev/null)  
  
  CANDS=()  
  local dev type fstype size pk mnt  
  while read -r dev type fstype size pk mnt; do  
    [ "$type" = "part" ] || continue  
    [ "$(basename "$pk")" = "$root_disk" ] && continue  # skip boot disk  
    [ "$mnt" = "$DATA_MOUNT" ] && continue            # already our mount  
    case "$dev" in /dev/mmcblk*|/dev/loop*|/dev/zram*) continue ;; esac  
    CANDS+=("$dev|$size|${fstype:-none}|$pk")  
  done <<<"$(printf '%s\n' "${ROWS[@]}")"  
  
  if [ "${#CANDS[@]}" -eq 0 ]; then  
    die "No usable SSD partition found (boot disk excluded). Plug the SSD in and re-run."  
  fi  
  
  echo ""  
  echo "Detected candidate SSD partitions:"  
  local i  
  for i in "${!CANDS[@]}"; do  
    IFS='|' read -r cdev csize cfs _cpk <<<"${CANDS[$i]}"  
    echo "  [$((i + 1))]  ${cdev}  (${csize}, filesystem: ${cfs})"  
  done  
  echo ""  
  
  local choice=""  
  while true; do  
    read -r -p "Which partition is the DizerCore SSD? [1-${#CANDS[@]}] " choice </dev/tty || true  
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#CANDS[@]}" ]; then  
      IFS='|' read -r SSD_DEV _sz _fs SSD_DISK <<<"${CANDS[$((choice - 1))]}"  
      SSD_DISK="/dev/$(basename "$SSD_DISK")"  
      return 0  
    fi  
    warn "Enter a number between 1 and ${#CANDS[@]}."  
  done  
}  
  
# ------------------------------------------------------------------  
# wipe_ssd — ERASE the whole picked disk: new GPT label, one ext4  
# partition filling the disk. Requires typing ERASE to proceed.  
# Sets SSD_PART to the freshly created partition.  
# ------------------------------------------------------------------  
wipe_ssd() {  
  echo ""  
  warn "INSTALL = FULL WIPE. EVERYTHING on ${SSD_DISK} will be destroyed:"  
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT "$SSD_DISK" || true  
  echo ""  
  local reply=""  
  read -r -p "Type ERASE to wipe ${SSD_DISK} clean: " reply </dev/tty || true  
  [ "$reply" = "ERASE" ] || { echo "Aborted."; exit 0; }  
  
  ok "Unmounting everything on ${SSD_DISK}"  
  sudo umount "${SSD_DISK}"* 2>/dev/null || true  
  
  ok "Wiping ${SSD_DISK} (new GPT label + single ext4 partition)"  
  sudo wipefs -a "$SSD_DISK"  
  sudo parted -s "$SSD_DISK" mklabel gpt  
  sudo parted -s "$SSD_DISK" mkpart primary ext4 0% 100%  
  sudo partprobe "$SSD_DISK" || true  
  sleep 2  
  
  # New partition node: nvme/mmcblk style disks append pN, others append N.  
  if [[ "$SSD_DISK" =~ (nvme|mmcblk|loop) ]]; then  
    SSD_PART="${SSD_DISK}p1"  
  else  
    SSD_PART="${SSD_DISK}1"  
  fi  
  [ -b "$SSD_PART" ] || die "Expected new partition ${SSD_PART} not found after wipe."  
  
  ok "Formatting ${SSD_PART} as ext4 (label ${SSD_LABEL})"  
  sudo mkfs.ext4 -F -L "$SSD_LABEL" "$SSD_PART"  
}  
  
# ==================================================================  
# 0. Role picker — one installer for both pis  
# ==================================================================  
banner "${APP_NAME} installer"  
require_tty  
  
echo ""  
echo "Which role is this machine?"  
echo "  [1] DizerCore-AI.Code-Agent   (runs the AI pipeline + web UI)"  
echo "  [2] DizerCore-AI.Build-Agent  (remote build executor)"  
while true; do  
  read -r -p "Role [1-2]: " ROLE_CHOICE </dev/tty || true  
  case "$ROLE_CHOICE" in  
    1)  
      ok "Role: DizerCore-AI.Code-Agent"  
      break  
      ;;  
    2)  
      ok "Role: DizerCore-AI.Build-Agent — fetching install-executor.sh"  
      EXEC_TMP="$(mktemp /tmp/install-executor.XXXXXX.sh)"  
      curl -fsSL "${EXECUTOR_URL}?nocache=$(date +%s)" -o "$EXEC_TMP" || die "Could not fetch install-executor.sh"  
      tr -d '\r' < "$EXEC_TMP" > "${EXEC_TMP}.clean"  
      chmod +x "${EXEC_TMP}.clean"  
      # exec replaces this script — the executor runs from a real file  
      # so every read prompt works even under curl|bash invocation.  
      exec bash "${EXEC_TMP}.clean"  
      ;;  
  esac  
  warn "Enter 1 or 2."  
done  
  
# ==================================================================  
# 1. Detect and remove a previous install  
# ==================================================================  
PREV=0  
systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service" && PREV=1  
[ -d "$APP_DIR" ] && PREV=1  
[ -f "$ENV_FILE" ] && PREV=1  
[ -d "$DATA_DIR" ] && PREV=1  
  
if [ "$PREV" -eq 1 ]; then  
  echo ""  
  warn "A previous ${APP_NAME} install was detected."  
  echo "This will STOP the service, remove ${APP_DIR}, remove the systemd unit,"  
  echo "and ERASE all data in ${DATA_DIR} (env file + databases)."  
  echo "The fstab mount entry for ${DATA_MOUNT} will also be removed and the SSD unmounted."  
  echo ""  
  
  # Offer to save the API keys to the SD card BEFORE they are wiped.  
  if [ -f "$ENV_FILE" ] && [ ! -f "$ENV_BAK" ]; then  
    if confirm "Save your API keys to ${ENV_BAK} (on the SD card, survives this wipe)?"; then  
      cp "$ENV_FILE" "$ENV_BAK"  
      chmod 600 "$ENV_BAK"  
      ok "Keys backed up to ${ENV_BAK}"  
    fi  
  elif [ -f "$ENV_BAK" ]; then  
    ok "Existing key backup found at ${ENV_BAK} — will offer to restore it later."  
  fi  
  
  if ! confirm "Remove the previous install AND all its data?"; then  
    echo "Aborted."  
    exit 0  
  fi  
  ok "Removing previous install"  
  sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true  
  sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true  
  sudo rm -f "$SERVICE"  
  sudo systemctl daemon-reload || true  
  sudo systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true  
  rm -rf "$APP_DIR"  
  sudo rm -rf "$DATA_DIR"                          # env file + all DBs (before unmount)  
  sudo sed -i "\|${DATA_MOUNT}|d" /etc/fstab       # drop the mount entry  
  sudo umount "$DATA_MOUNT" 2>/dev/null || true  
  sudo systemctl daemon-reload || true  
fi  
if ! confirm "Proceed with a fresh install of ${APP_NAME}?"; then  
  echo "Aborted."  
  exit 0  
fi  
  
# ==================================================================  
# 2. System deps  
# ==================================================================  
ok "Installing system dependencies"  
sudo apt-get update -y  
sudo apt-get install -y git python3-venv python3-pip util-linux parted curl  
  
# ==================================================================  
# 3. UAS quirk hotfix — applied AUTOMATICALLY; requires one reboot,  
#    then re-run this installer.  
# ==================================================================  
if ! grep -q "$QUIRK" "$CMDLINE" 2>/dev/null; then  
  ok "Applying USB UAS quirk hotfix for the SSD bridge (reboot required)"  
  sudo sed -i "s|\$| ${QUIRK}|" "$CMDLINE"  
  echo ""  
  warn "Hotfix applied. REBOOT now, then re-run this installer:"  
  echo "    sudo reboot"  
  exit 0  
fi  
  
# ==================================================================  
# 4. Detect the SSD — then ALWAYS wipe it clean (typed ERASE required)  
# ==================================================================  
SSD_DEV=""  
SSD_DISK=""  
SSD_PART=""  
pick_ssd  
ok "Using ${SSD_DISK} (picked partition ${SSD_DEV}) for DizerCore data"  
wipe_ssd  
ok "Wipe complete; using ${SSD_PART}"  
  
# ==================================================================  
# 5. Mount the SSD by UUID  
# ==================================================================  
ok "Mounting the SSD"  
NEW_UUID="$(sudo blkid -s UUID -o value "$SSD_PART")"  
[ -n "$NEW_UUID" ] || die "Could not read UUID of ${SSD_PART}"  
  
sudo mkdir -p "$DATA_MOUNT"  
sudo sed -i "\|${DATA_MOUNT}|d" /etc/fstab  
echo "UUID=${NEW_UUID}  ${DATA_MOUNT}  ext4  defaults,nofail,x-systemd.device-timeout=10  0  2" | sudo tee -a /etc/fstab >/dev/null  
sudo systemctl daemon-reload  
sudo mount -a  
findmnt "$DATA_MOUNT" >/dev/null || die "SSD failed to mount at ${DATA_MOUNT}"  
  
sudo mkdir -p "$DATA_DIR"  
sudo chown "$USER_NAME:$USER_NAME" "$DATA_DIR"  
  
# ==================================================================  
# 6. Clone repo + stamp version + freshness check  
# ==================================================================  
ok "Cloning ${REPO}"  
git clone --branch "$BRANCH" "$REPO" "$APP_DIR"  
  
ok "Stamping version"  
# VERSION = 3 fields: SHA TIMESTAMP REPO  
echo "$(cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo unknown) $(date -u +%Y-%m-%dT%H:%M:%SZ) ${REPO}" > "$APP_DIR/VERSION"  
  
ok "Checking whether the install is on the latest commit"  
LOCAL_FULL="$( cd "$APP_DIR" && git rev-parse HEAD 2>/dev/null || echo "" )"  
LOCAL_SHORT="$( cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo "unknown" )"  
REMOTE_FULL="$( git ls-remote "$REPO" "refs/heads/${BRANCH}" 2>/dev/null | awk '{print $1}' )" || true  
  
if [ -z "$REMOTE_FULL" ]; then  
  warn "Could not reach GitHub to verify latest commit; skipping freshness check."  
elif [ "$REMOTE_FULL" = "$LOCAL_FULL" ]; then  
  ok "Installed commit ${LOCAL_SHORT} is the latest on ${BRANCH}."  
else  
  warn "Installed commit ${LOCAL_SHORT} is NOT the latest. Remote ${BRANCH} HEAD is ${REMOTE_FULL:0:7}."  
fi  
  
[ -f "$APP_DIR/$ENTRYPOINT" ] || die "Entrypoint ${ENTRYPOINT} not found in repo."  
if [ ! -f "$APP_DIR/static/dizercore.png" ]; then  
  warn "static/dizercore.png not found; dashboard logo and favicon will be blank."  
fi  
  
# ==================================================================  
# 7. Python venv + deps  
# ==================================================================  
ok "Setting up Python venv"  
python3 -m venv "$APP_DIR/venv"  
"$APP_DIR/venv/bin/pip" install --upgrade pip  
if [ -f "$APP_DIR/requirements.txt" ]; then  
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"  
else  
  "$APP_DIR/venv/bin/pip" install fastapi uvicorn httpx google-genai python-multipart  
fi  
  
# ==================================================================  
# 8. API keys — restore from SD backup if the user says yes,  
#    otherwise prompt and save a fresh backup.  
#    The WEB UI ADMIN password is ALWAYS asked, even on key restore.  
# ==================================================================  
SKIP_KEYS=0  
if [ -f "$ENV_BAK" ]; then  
  ok "Saved API keys found on the SD card (${ENV_BAK})"  
  if confirm "Reuse saved keys instead of typing them again?"; then  
    cp "$ENV_BAK" "$ENV_FILE"  
    chmod 600 "$ENV_FILE"  
    ok "Restored keys to ${ENV_FILE}"  
    SKIP_KEYS=1  
    # Stale-backup guard — every key Config.from_env() requires must be  
    # present with a non-empty value, otherwise fall back to prompting.  
    for req in "${REQUIRED_KEYS[@]}"; do  
      if ! grep -q "^${req}=." "$ENV_FILE"; then  
        warn "Backup is missing ${req} — will prompt for keys."  
        SKIP_KEYS=0  
      fi  
    done  
  fi  
fi  
  
if [ "$SKIP_KEYS" -eq 0 ]; then  
  ok "Enter your API keys"  
  read -r -p "1. Google Gemini Studio API key: " GEMINI_API_KEY </dev/tty  
  read -r -p "2. OpenAI API key (ChatGPT coder, starts with sk-): " OPENAI_API_KEY </dev/tty  
  read -r -p "3. Groq API key (starts with gsk_): " GROQ_API_KEY </dev/tty  
  read -r -p "4. OpenRouter JUDGE API key (judging only, required): " OPENROUTER_API_KEY_JUDGE </dev/tty  
  [ -n "$OPENROUTER_API_KEY_JUDGE" ] || die "OpenRouter JUDGE key is required — the judge pool runs on OpenRouter."  
fi  
  
# Admin password is always prompted — even when keys were restored.  
# Strip '|' since it is the sed delimiter used by set_env below.  
read -r -p "Web UI ADMIN password (gates /delete-account page): " WEBUI_ADMIN_PASSWORD </dev/tty  
WEBUI_ADMIN_PASSWORD="${WEBUI_ADMIN_PASSWORD//|/}"  
  
# ==================================================================  
# 9. Write env file  
# ==================================================================  
if [ "$SKIP_KEYS" -eq 0 ]; then  
  ok "Writing env file"  
  {  
    printf 'DIZER_DATA_DIR=%s\n' "$DATA_DIR"  
    printf 'PORT=%s\n' "$PORT"  
    printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY"  
    printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY"  
    printf 'GROQ_API_KEY=%s\n' "$GROQ_API_KEY"  
    printf 'OPENROUTER_API_KEY_JUDGE=%s\n' "$OPENROUTER_API_KEY_JUDGE"  
    printf 'WEBUI_ADMIN_PASSWORD=%s\n' "$WEBUI_ADMIN_PASSWORD"  
  } > "$ENV_FILE"  
  chmod 600 "$ENV_FILE"  
  
  # Keep a copy on the SD card for the next reinstall.  
  cp "$ENV_FILE" "$ENV_BAK"  
  chmod 600 "$ENV_BAK"  
  ok "Keys backed up to ${ENV_BAK} (SD card — survives future SSD wipes)"  
else  
  # Keys were restored — apply the freshly typed admin password and  
  # force-rewrite path/port so stale backup values can't linger.  
  ok "Applying settings to restored env file"  
  set_env "WEBUI_ADMIN_PASSWORD" "$WEBUI_ADMIN_PASSWORD"  
  set_env "DIZER_DATA_DIR"       "$DATA_DIR"  
  set_env "PORT"                 "$PORT"  
  ok "Admin password and paths updated in ${ENV_FILE}"  
fi  
  
# ==================================================================  
# 10. DizerCore-AI.Build-Agent (optional) — remote build executor pi.  
#     SSH keypair + reachability smoke test by IP. The Build-Agent pi  
#     must already be set up (install-executor.sh — it prints its IP  
#     at the end). Type 0.0.0.0 to skip.  
# ==================================================================  
BUILD_KEY="${HOME}/.ssh/dizercorebuild_ed25519"  
BUILD_HOST=""  
BUILD_ENABLED="false"  
  
echo ""  
echo "The Build-Agent prints its IP at the end of install-executor.sh."  
ask_ip "Build-Agent IP address (type 0.0.0.0 to skip)" ""  
  
if [ "$REPLY_IP" = "0.0.0.0" ]; then  
  ok "Build executor skipped — builds disabled"  
else  
  BUILD_HOST="$REPLY_IP"  
  ok "Setting up SSH key for Build-Agent at ${BUILD_HOST}"  
  
  mkdir -p "${HOME}/.ssh"  
  chmod 700 "${HOME}/.ssh"  
  if [ ! -f "$BUILD_KEY" ]; then  
    ssh-keygen -t ed25519 -N "" -f "$BUILD_KEY" -C "code-agent->build-agent" >/dev/null  
    ok "Generated ${BUILD_KEY}"  
  else  
    ok "Reusing existing key ${BUILD_KEY}"  
  fi  
  
  echo ""  
  banner "Add this public key on the Build-Agent (${BUILD_HOST})"  
  echo " On the Build-Agent pi, append the line below to:"  
  echo "   /home/${BUILD_SSH_USER}/.ssh/authorized_keys"  
  echo " (install-executor.sh created the ${BUILD_SSH_USER} user and .ssh dir)"  
  echo ""  
  cat "${BUILD_KEY}.pub"  
  echo ""  
  read -r -p "Press ENTER once the key is installed on the Build-Agent... " _ </dev/tty || true  
  
  # Smoke test — BatchMode=yes so it fails fast instead of prompting.  
  if ssh -i "$BUILD_KEY" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "${BUILD_SSH_USER}@${BUILD_HOST}" true 2>/dev/null; then  
    ok "SSH smoke test passed — Build-Agent reachable"  
    BUILD_ENABLED="true"  
  else  
    warn "SSH to ${BUILD_SSH_USER}@${BUILD_HOST} failed — leaving BUILD_ENABLED=false."  
    warn "Check: Build-Agent powered on, install-executor.sh ran, key added to"  
    warn "/home/${BUILD_SSH_USER}/.ssh/authorized_keys. Re-run installer to retry."  
  fi  
  
  set_env "BUILD_HOST"     "$BUILD_HOST"  
  set_env "BUILD_USER"     "$BUILD_SSH_USER"  
  set_env "BUILD_KEY_PATH" "$BUILD_KEY"  
  set_env "BUILD_ROOT"     "/mnt/build"  
fi  
  
# Always write the switch + defaults so the env file is self-describing.  
set_env "BUILD_ENABLED"      "$BUILD_ENABLED"  
set_env "BUILD_MAX_RETRIES"  "2"  
set_env "BUILD_TIMEOUT_S"    "600"  
set_env "BUILD_TIMEOUT_TREE" "7200"  
set_env "BUILD_JOBS"         "4"  
set_env "BUILD_MEM_MB"       "3072"  
set_env "BUILD_CPU_S"        "3600"  
  
# ==================================================================  
# 11. Install systemd service  
# ==================================================================  
ok "Installing systemd service"  
{  
  printf '[Unit]\n'  
  printf 'Description=%s\n' "$APP_NAME"  
  printf 'After=network-online.target\n'  
  printf 'Wants=network-online.target\n'  
  printf 'RequiresMountsFor=%s\n' "$DATA_MOUNT"  
  printf '\n'  
  printf '[Service]\n'  
  printf 'User=%s\n' "$USER_NAME"  
  printf 'WorkingDirectory=%s\n' "$APP_DIR"  
  printf 'EnvironmentFile=%s\n' "$ENV_FILE"  
  printf 'ExecStart=%s/venv/bin/python3 %s/%s\n' "$APP_DIR" "$APP_DIR" "$ENTRYPOINT"  
  printf 'Restart=always\n'  
  printf 'RestartSec=3\n'  
  printf 'StandardOutput=journal\n'  
  printf 'StandardError=journal\n'  
  printf '\n'  
  printf '[Install]\n'  
  printf 'WantedBy=multi-user.target\n'  
} | sudo tee "$SERVICE" >/dev/null  
  
sudo systemctl daemon-reload  
sudo systemctl enable "$SERVICE_NAME"  
sudo systemctl restart "$SERVICE_NAME"  
  
# ==================================================================  
# 12. Print the URL  
# ==================================================================  
IP="$(hostname -I | awk '{print $1}')"  
echo ""  
banner "${APP_NAME} Code-Agent is running"  
echo " Open:       http://${IP}:${PORT}/"  
echo " Live logs:  journalctl -u ${SERVICE_NAME} -f"  
if [ "$BUILD_ENABLED" = "true" ]; then  
  echo " Builds:     remote on Build-Agent at ${BUILD_HOST}"  
else  
  echo " Builds:     disabled (no Build-Agent configured)"  
fi  
echo "============================================================"
