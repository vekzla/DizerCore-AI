#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install.sh — one-shot installer for Raspberry Pi 5 (headless).  
# Auto-detects plugged-in SSDs (excludes the SD card / boot disk), lets  
# the user pick the target, applies the UAS quirk hotfix automatically,  
# formats ext4 ONLY if needed (with an explicit erase warning), mounts  
# by UUID at /mnt/dizerdata, writes the env file (incl. optional  
# dedicated OpenRouter JUDGE key), installs the systemd service.  
# ==================================================================  
set -Eeuo pipefail  
  
REPO="https://github.com/vekzla/DizerCore-AI.git"  
BRANCH="main"  
APP_NAME="DizerCoreAI"  
ENTRYPOINT="dizercoreai.py"  
SERVICE_NAME="dizercore"  
APP_DIR="${HOME}/DizerCore-AI"  
DATA_MOUNT="/mnt/dizerdata"  
PORT="8000"  
  
# ---------- pretty output ----------  
banner(){ echo; echo "============================================================"; echo " $*"; echo "============================================================"; }  
ok(){     echo "==> $*"; }  
warn(){   echo "!!  $*"; }  
die(){    echo "ERROR: $*" >&2; exit 1; }  
need(){   command -v "$1" >/dev/null 2>&1 || die "Missing '$1' (try: sudo apt install $1)"; }  
  
banner "${APP_NAME} installer"  
echo " Repo:      ${REPO} (${BRANCH})"  
echo " App dir:   ${APP_DIR}"  
echo " Data dir:  ${DATA_MOUNT}"  
echo " Service:   ${SERVICE_NAME} (port ${PORT})"  
  
# ==================================================================  
# 1. Preflight  
# ==================================================================  
for c in git curl lsblk awk sed findmnt; do need "$c"; done  
if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then  
  echo " NOTE: sudo will prompt for your password when needed."  
fi  
  
# ==================================================================  
# 2. Remove any previous install  
# ==================================================================  
ok "Removing any previous install"  
sudo systemctl stop    "$SERVICE_NAME" 2>/dev/null || true  
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true  
sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"  
sudo systemctl daemon-reload 2>/dev/null || true  
sudo rm -rf "$APP_DIR"  
sudo umount "$DATA_MOUNT" 2>/dev/null || true  
sudo sed -i "\|${DATA_MOUNT}|d" /etc/fstab || true  
sudo rm -rf "$DATA_MOUNT"  
  
# ==================================================================  
# 3. Pick a target disk  
# ==================================================================  
ok "Boot disk detected: $(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" 2>/dev/null || echo unknown) (excluded from choices)"  
  
mapfile -t DISKS < <(lsblk -dn -o NAME,SIZE,TYPE,TRAN,MODEL 2>/dev/null | awk '$3=="disk" && $1 !~ /^(mmcblk0|loop|ram)/ {model=""; for (i=5; i<=NF; i++) model=(model ? model" " : "") $i; printf "/dev/%s|%s|%s|%s\n", $1, $2, $4, model}')  
[ "${#DISKS[@]}" -gt 0 ] || die "No candidate disks found. Is the SSD plugged in (USB adapter powered)?"  
  
echo ""  
echo "Available disks:"  
for i in "${!DISKS[@]}"; do  
  IFS='|' read -r d sz tr mo <<<"${DISKS[$i]}"  
  printf "  [%s] %-11s %-7s %s %s\n" "$i" "$d" "$sz" "$tr" "$mo"  
done  
echo ""  
read -r -p "Pick a disk [0-$((${#DISKS[@]}-1))]: " IDX  
[[ "$IDX" =~ ^[0-9]+$ ]] && [ "$IDX" -lt "${#DISKS[@]}" ] || die "Invalid choice."  
IFS='|' read -r DISK _ _ _ <<<"${DISKS[$IDX]}"  
ok "Using ${DISK}"  
  
# ==================================================================  
# 4. UAS quirk hotfix (auto-detect, safe to skip)  
# ==================================================================  
ok "Applying UAS quirk check"  
IDS="$(lsusb | awk '{print $6}')"  
VIDPID=""  
for id in $IDS; do  
  case "$id" in *:*) VIDPID="$id"; break;; esac  
done  
if [ -n "$VIDPID" ]; then  
  echo "options usb-storage quirks=${VIDPID}:u" | sudo tee /etc/modprobe.d/uas-quirk.conf >/dev/null  
  ok "Wrote /etc/modprobe.d/uas-quirk.conf for ${VIDPID} (takes effect on next reboot)"  
else  
  warn "Could not detect USB bridge IDs; skipping UAS quirk."  
fi  
  
# ==================================================================  
# 5. Partition + format if needed  
# ==================================================================  
ok "Partitioning ${DISK} (GPT, single ext4 partition)"  
sudo parted -s "$DISK" mklabel gpt  
sudo parted -s "$DISK" mkpart primary ext4 1MiB 100%  
sudo partprobe "$DISK" || true  
sleep 1  
PART="${DISK}1"; [ -b "$PART" ] || PART="${DISK}p1"  
  
FSTYPE="$(lsblk -no FSTYPE "$PART" 2>/dev/null || true)"  
if [ -z "$FSTYPE" ]; then  
  warn "${PART} has no filesystem."  
  read -r -p "Type ERASE to format ${PART} as ext4 (destroys all data): " CONFIRM  
  [ "$CONFIRM" = "ERASE" ] || die "Aborted — disk not formatted."  
  sudo mkfs.ext4 -F -L dizerdata "$PART"  
else  
  ok "Existing filesystem on ${PART}: ${FSTYPE} — keeping data"  
fi  
  
# ==================================================================  
# 6. Mount by UUID at /mnt/dizerdata  
# ==================================================================  
UUID="$(sudo blkid -s UUID -o value "$PART")"  
[ -n "$UUID" ] || die "Could not read UUID from ${PART}."  
sudo mkdir -p "$DATA_MOUNT"  
sudo mount "$PART" "$DATA_MOUNT"  
grep -q "$UUID" /etc/fstab || echo "UUID=${UUID} ${DATA_MOUNT} ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab >/dev/null  
ok "Mounted ${PART} at ${DATA_MOUNT} (UUID ${UUID})"  
  
# ==================================================================  
# 7. Collect API keys + write env file  
# ==================================================================  
ok "Collecting API keys"  
read -r -p "GEMINI_API_KEY: "            GEMINI_API_KEY  
read -r -p "OPENROUTER_API_KEY_CODER: "  OPENROUTER_API_KEY_CODER  
read -r -p "GROQ_API_KEY: "              GROQ_API_KEY  
read -r -p "OPENROUTER_API_KEY_JUDGE (optional, Enter to reuse coder key): " OPENROUTER_API_KEY_JUDGE || true  
read -r -p "WEBUI_ADMIN_PASSWORD (for /delete-account): " WEBUI_ADMIN_PASSWORD  
  
DATA_DIR="${DATA_MOUNT}/dizercore"  
ENV_FILE="${DATA_DIR}/dizercore.env"  
sudo mkdir -p "$DATA_DIR"  
{  
  echo "DIZER_DATA_DIR=${DATA_DIR}"  
  echo "GEMINI_API_KEY=${GEMINI_API_KEY}"  
  echo "OPENROUTER_API_KEY_CODER=${OPENROUTER_API_KEY_CODER}"  
  echo "GROQ_API_KEY=${GROQ_API_KEY}"  
  echo "OPENROUTER_API_KEY_JUDGE=${OPENROUTER_API_KEY_JUDGE}"  
  echo "WEBUI_ADMIN_PASSWORD=${WEBUI_ADMIN_PASSWORD}"  
} | sudo tee "$ENV_FILE" >/dev/null  
sudo chmod 600 "$ENV_FILE"  
ok "Wrote ${ENV_FILE}"  
  
# ==================================================================  
# 8. Clone repo, venv, deps, stamp VERSION  
# ==================================================================  
ok "Cloning ${REPO}"  
git clone --branch "$BRANCH" "$REPO" "$APP_DIR"  
  
ok "Stamping version"  
SHA="$( cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo unknown )"  
printf '%s %s %s\n' "$SHA" "$(date -u +%Y-%m-%dT%H:%MZ)" "$REPO" > "$APP_DIR/VERSION"  
  
ok "Checking whether the install is on the latest commit"  
REMOTE_FULL="$( git ls-remote "$REPO" "refs/heads/${BRANCH}" 2>/dev/null | awk '{print $1}' )" || true  
if [ -z "$REMOTE_FULL" ]; then  
  warn "Could not reach GitHub to verify latest commit; skipping freshness check."  
elif [ "$REMOTE_FULL" = "$( cd "$APP_DIR" && git rev-parse HEAD 2>/dev/null )" ]; then  
  ok "Installed commit ${SHA} is the latest on ${BRANCH}."  
else  
  warn "Installed commit ${SHA} is NOT the latest. Remote ${BRANCH} HEAD is ${REMOTE_FULL:0:7}."  
fi  
  
[ -f "$APP_DIR/$ENTRYPOINT" ] || die "Entrypoint ${ENTRYPOINT} not found in repo."  
if [ ! -f "$APP_DIR/static/dizercore.png" ]; then  
  warn "static/dizercore.png not found; dashboard logo and favicon will be blank."  
fi  
  
ok "Creating venv + installing dependencies"  
python3 -m venv "$APP_DIR/venv" || { sudo apt-get update && sudo apt-get install -y python3-venv && python3 -m venv "$APP_DIR/venv"; }  
"$APP_DIR/venv/bin/pip" install --upgrade pip  
if [ -f "$APP_DIR/requirements.txt" ]; then  
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"  
else  
  "$APP_DIR/venv/bin/pip" install fastapi uvicorn httpx google-genai python-multipart  
fi  
  
# ==================================================================  
# 9. systemd service  
# ==================================================================  
SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"  
ok "Writing ${SERVICE}"  
{  
  printf '[Unit]\n'  
  printf 'Description=DizerCoreAI\n'  
  printf 'After=network-online.target %s.mount\n' "$(basename "$DATA_MOUNT")"  
  printf 'Wants=network-online.target\n'  
  printf 'RequiresMountsFor=%s\n' "$DATA_MOUNT"  
  printf '\n'  
  printf '[Service]\n'  
  printf 'Type=simple\n'  
  printf 'User=%s\n' "$(whoami)"  
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
