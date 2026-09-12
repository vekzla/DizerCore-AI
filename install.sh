#!/usr/bin/env bash  
# DizerCoreAI one-shot installer for Raspberry Pi 5 (headless).  
# Run: curl -fsSL https://raw.githubusercontent.com/vekzla/DizerCore-AI/main/install.sh | tr -d '\r' | bash  
set -Eeuo pipefail  
  
# ==================================================================  
# Config  
# ==================================================================  
REPO="https://github.com/vekzla/DizerCore-AI.git"  
BRANCH="main"  
APP_NAME="DizerCoreAI"  
ENTRYPOINT="dizercoreai.py"  
SERVICE_NAME="dizercore"  
PORT="8000"  
  
SSD_DEV="/dev/sda1"  
SSD_LABEL="DizerCore"  
DATA_MOUNT="/mnt/dizerdata"  
DATA_DIR="${DATA_MOUNT}/dizercore"  
ENV_FILE="${DATA_DIR}/dizercore.env"  
  
APP_DIR="${HOME}/DizerCore-AI"  
SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"  
USER_NAME="$(whoami)"  
  
QUIRK="usb-storage.quirks=152d:0578:u"  
CMDLINE="/boot/firmware/cmdline.txt"  
  
# ==================================================================  
# Helpers  
# ==================================================================  
banner() {  
  echo "============================================================"  
  echo " $1"  
  echo "============================================================"  
}  
ok()   { echo "==> $1"; }  
warn() { echo "!!  $1" >&2; }  
die()  { echo "XX  $1" >&2; exit 1; }  
  
confirm() {  
  local reply  
  read -r -p "$1 [y/N] " reply </dev/tty  
  [[ "$reply" =~ ^[Yy]$ ]]  
}  
  
require_tty() {  
  [ -e /dev/tty ] || die "No TTY available; run this in an interactive shell."  
}  
  
# ==================================================================  
# 0. Detect and remove a previous install  
# ==================================================================  
banner "${APP_NAME} installer"  
require_tty  
  
PREV=0  
if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then PREV=1; fi  
if [ -d "$APP_DIR" ]; then PREV=1; fi  
if [ -f "$ENV_FILE" ]; then PREV=1; fi  
if [ -d "$DATA_DIR" ]; then PREV=1; fi  
  
if [ "$PREV" -eq 1 ]; then  
  echo ""  
  warn "A previous ${APP_NAME} install was detected."  
  echo "This will STOP the service, remove ${APP_DIR}, remove the systemd unit,"  
  echo "and (if you confirm) FORMAT the SSD at ${SSD_DEV}, ERASING all its data."  
  echo ""  
  if confirm "Remove the previous install and FORMAT the SSD?"; then  
    ok "Removing previous install"  
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true  
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true  
    sudo rm -f "$SERVICE"  
    sudo systemctl daemon-reload || true  
    sudo systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true  
    rm -rf "$APP_DIR"  
    sudo umount "$DATA_MOUNT" 2>/dev/null || true  
    FORMAT_SSD=1  
  else  
    echo "Aborted."  
    exit 0  
  fi  
else  
  FORMAT_SSD=1  
fi  
  
if ! confirm "Proceed with a fresh install of ${APP_NAME}?"; then  
  echo "Aborted."  
  exit 0  
fi  
  
# ==================================================================  
# 1. System deps  
# ==================================================================  
ok "Installing system dependencies"  
sudo apt-get update -y  
sudo apt-get install -y git python3-venv python3-pip  
  
# ==================================================================  
# 2. Apply UAS quirk (needs reboot before first format)  
# ==================================================================  
if ! grep -q "$QUIRK" "$CMDLINE" 2>/dev/null; then  
  ok "Applying USB UAS quirk for the SSD bridge (reboot required)"  
  sudo sed -i "s|\$| ${QUIRK}|" "$CMDLINE"  
  echo ""  
  warn "Quirk applied. REBOOT now, then re-run this installer:"  
  echo "    sudo reboot"  
  exit 0  
fi  
  
# ==================================================================  
# 3. Format the SSD to ext4  
# ==================================================================  
if [ "${FORMAT_SSD:-0}" -eq 1 ]; then  
  ok "Formatting ${SSD_DEV} as ext4 (label ${SSD_LABEL})"  
  sudo umount "$SSD_DEV" 2>/dev/null || true  
  sudo mkfs.ext4 -F -L "$SSD_LABEL" "$SSD_DEV"  
fi  
  
# ==================================================================  
# 4. Mount the SSD by UUID  
# ==================================================================  
ok "Mounting the SSD"  
NEW_UUID="$(sudo blkid -s UUID -o value "$SSD_DEV")"  
[ -n "$NEW_UUID" ] || die "Could not read UUID of ${SSD_DEV}"  
  
sudo mkdir -p "$DATA_MOUNT"  
sudo sed -i "\|${DATA_MOUNT}|d" /etc/fstab  
echo "UUID=${NEW_UUID}  ${DATA_MOUNT}  ext4  defaults,nofail,x-systemd.device-timeout=10  0  2" | sudo tee -a /etc/fstab >/dev/null  
sudo systemctl daemon-reload  
sudo mount -a  
findmnt "$DATA_MOUNT" >/dev/null || die "SSD failed to mount at ${DATA_MOUNT}"  
  
sudo mkdir -p "$DATA_DIR"  
sudo chown "$USER_NAME:$USER_NAME" "$DATA_DIR"  
  
# ==================================================================  
# 5.0. Clone the repo  
# ==================================================================  
ok "Cloning ${REPO}"  
git clone --branch "$BRANCH" "$REPO" "$APP_DIR"  

# ==================================================================  
# 5.1. Stamp the installed version (short git SHA) for /version  
# ==================================================================  
ok "Stamping version"  
( cd "$APP_DIR" && git rev-parse --short HEAD > VERSION 2>/dev/null ) \  
  || echo "unknown" > "$APP_DIR/VERSION"
  
# Confirm the entrypoint and logo made it through the clone.  
[ -f "$APP_DIR/$ENTRYPOINT" ] || die "Entrypoint ${ENTRYPOINT} not found in repo; check the file name/case."  
if [ ! -f "$APP_DIR/static/dizercore.png" ]; then  
  warn "static/dizercore.png not found; the dashboard/login logo and favicon will be blank."  
fi  
  
# ==================================================================  
# 6. Python venv + deps  
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
# 7. Prompt for API keys  
# ==================================================================  
ok "Enter your API keys"  
read -r -p "1. Google Gemini Studio API key: " GEMINI_API_KEY </dev/tty  
read -r -p "2. OpenRouter API key: " OPENROUTER_API_KEY </dev/tty  
read -r -p "3. Groq API key (starts with gsk_): " GROQ_API_KEY </dev/tty  
  
# ==================================================================  
# 8. Write env file  
# ==================================================================  
ok "Writing env file"  
{  
  printf 'DIZER_DATA_DIR=%s\n' "$DATA_DIR"  
  printf 'PORT=%s\n' "$PORT"  
  printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY"  
  printf 'OPENROUTER_API_KEY=%s\n' "$OPENROUTER_API_KEY"  
  printf 'GROQ_API_KEY=%s\n' "$GROQ_API_KEY"  
} > "$ENV_FILE"  
chmod 600 "$ENV_FILE"  
  
# ==================================================================  
# 9. Install systemd service  
# ==================================================================  
ok "Installing systemd service"  
{  
  printf '[Unit]\n'  
  printf 'Description=%s\n' "$APP_NAME"  
  printf 'After=network-online.target %s\n' "$DATA_MOUNT"  
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
# 10. Print the URL  
# ==================================================================  
IP="$(hostname -I | awk '{print $1}')"  
echo ""  
banner "${APP_NAME} is running"  
echo " Open:       http://${IP}:${PORT}/"  
echo " Live logs:  journalctl -u ${SERVICE_NAME} -f"  
echo "============================================================"
