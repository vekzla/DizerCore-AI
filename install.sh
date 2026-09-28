#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install.sh — one-shot installer for Raspberry Pi 5 (headless).  
# Auto-detects plugged-in SSDs (excludes the SD card / boot disk), lets  
# the user pick the target, applies the UAS quirk hotfix automatically,  
# formats ext4 ONLY if needed (with an explicit erase warning), mounts  
# by UUID at /mnt/dizerdata, writes the env file (incl. optional  
# dedicated OpenRouter JUDGE key), installs the systemd service.  
# Safe to run either as:  sudo bash install.sh  
#                    or:  curl ... | bash   (auto-elevates via sudo)  
# ==================================================================  
set -Eeuo pipefail  
  
# ---- auto-elevate: if not root, re-run under sudo ------------------  
# Works for both invocation styles:  
#   * interactive file run  -> exec sudo bash "$0"  
#   * curl | bash pipe      -> slurp remaining script from stdin, run as root  
if [ "$(id -u)" -ne 0 ]; then  
  echo "==> Not root; re-running with sudo..."  
  if [ -t 0 ]; then  
    exec sudo bash "$0" "$@"  
  else  
    exec sudo bash -c "set -Eeuo pipefail; $(cat)"  
  fi  
fi  
  
REPO="https://github.com/vekzla/DizerCore-AI.git"  
BRANCH="main"  
APP_NAME="DizerCoreAI"  
ENTRYPOINT="dizercoreai.py"  
APP_DIR="/opt/${APP_NAME}"  
DATA_MOUNT="/mnt/dizerdata"  
DATA_DIR="${DATA_MOUNT}/dizercore"  
ENV_FILE="${DATA_DIR}/dizercore.env"  
SERVICE_NAME="dizercore"  
SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"  
PORT="8000"  
QUIRKS_FILE="/etc/modprobe.d/uas-realtek-quirk.conf"  
FSTAB="/etc/fstab"  
INSTALLER_USER="${SUDO_USER:-$(id -un)}"  
MOUNTED=""  
  
# ---- helpers -------------------------------------------------------  
say()  { printf '%s\n' "$*"; }  
ok()   { printf '==> %s\n' "$*"; }  
warn() { printf 'WARN: %s\n' "$*" >&2; }  
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }  
banner() { printf '\n============================================================\n %s\n============================================================\n' "$*"; }  
  
cleanup_on_err() {  
  local rc=$?  
  if [ -n "$MOUNTED" ]; then  
    warn "Install failed — unmounting $MOUNTED"  
    umount "$MOUNTED" 2>/dev/null || true  
  fi  
  exit "$rc"  
}  
trap cleanup_on_err ERR  
  
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing dependency: $1"; }  
  
# ==================================================================  
# 0. Root + sanity  
# ==================================================================  
need_cmd git; need_cmd lsblk; need_cmd blkid; need_cmd mount; need_cmd awk  
need_cmd mkfs.ext4; need_cmd curl; need_cmd systemctl  
  
banner "${APP_NAME} installer"  
say " Repo:      ${REPO} (${BRANCH})"  
say " App dir:   ${APP_DIR}"  
say " Data dir:  ${DATA_MOUNT}"  
say " Service:   ${SERVICE_NAME} (port ${PORT})"  
  
# ==================================================================  
# 1. Remove any previous install (app dir only — SSD data preserved)  
# ==================================================================  
ok "Removing any previous install"  
rm -rf "$APP_DIR"  
  
# ==================================================================  
# 2. Detect SSDs (exclude the SD card / boot disk)  
# ==================================================================  
ok "Boot disk detected: $(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || echo '?') (excluded from choices)"  
  
mapfile -t DISKS < <(lsblk -dpno NAME,SIZE,MODEL,TRAN | awk '{print}' | grep -v "mmcblk" || true)  
# Filter: exclude the disk hosting / (boot device)  
BOOT_DISK="$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)"  
CANDIDATES=()  
for line in "${DISKS[@]}"; do  
  dev="$(awk '{print $1}' <<<"$line")"  
  base="$(basename "$dev")"  
  [ "$base" = "$BOOT_DISK" ] && continue  
  CANDIDATES+=("$line")  
done  
  
[ "${#CANDIDATES[@]}" -gt 0 ] || die "No candidate disks found. Plug in the SSD via USB and retry."  
  
echo ""  
say "Available disks:"  
for i in "${!CANDIDATES[@]}"; do  
  say "  [$i] ${CANDIDATES[$i]}"  
done  
echo ""  
read -r -p "Pick a disk [0-$((${#CANDIDATES[@]} - 1))]: " choice < /dev/tty  
[[ "$choice" =~ ^[0-9]+$ ]] || die "Invalid choice."  
[ "$choice" -ge 0 ] && [ "$choice" -lt "${#CANDIDATES[@]}" ] || die "Invalid choice."  
  
TARGET="$(awk '{print $1}' <<<"${CANDIDATES[$choice]}")"  
[ -b "$TARGET" ] || die "Not a block device: $TARGET"  
  
# ==================================================================  
# 3. UAS quirk hotfix (Realtek USB-SATA bridges stutter under UAS)  
# ==================================================================  
ok "Applying UAS quirk check"  
VIDPID="$(lsusb -d "" 2>/dev/null | awk '{print $6}' | head -n1 || true)"  
# Detect the bridge chip of the chosen device  
USBDEV="$(udevadm info --query=property --name="$TARGET" 2>/dev/null | grep -E '^ID_VENDOR_ID=|^ID_MODEL_ID=' || true)"  
VID="$(awk -F= '/^ID_VENDOR_ID=/{print $2}' <<<"$USBDEV" | head -n1)"  
PID="$(awk -F= '/^ID_MODEL_ID=/{print $2}' <<<"$USBDEV" | head -n1)"  
if [ -n "${VID:-}" ] && [ -n "${PID:-}" ]; then  
  printf 'options usb-storage quirks=%s:%s:u\n' "$VID" "$PID" | sudo tee "$QUIRKS_FILE" >/dev/null  
  ok "UAS quirk written for ${VID}:${PID} -> ${QUIRKS_FILE}"  
else  
  warn "Could not detect USB bridge IDs; skipping UAS quirk."  
fi  
  
# ==================================================================  
# 4. Partition + format ext4 ONLY if needed (explicit erase warning)  
# ==================================================================  
PART="${TARGET}1"  
if blkid "$PART" >/dev/null 2>&1; then  
  FSTYPE="$(blkid -o value -s TYPE "$PART")"  
  ok "Existing filesystem on ${PART}: ${FSTYPE} — keeping data"  
else  
  warn "About to ERASE ALL DATA on ${TARGET} and create a single ext4 partition."  
  read -r -p "Type YES to continue: " confirm < /dev/tty  
  [ "$confirm" = "YES" ] || die "Aborted by user."  
  ok "Partitioning ${TARGET}"  
  printf 'o\nn\np\n1\n\n\nw\n' | fdisk "$TARGET" >/dev/null  
  partprobe "$TARGET" || true  
  sleep 2  
  [ -b "$PART" ] || die "Partition ${PART} did not appear."  
  ok "Formatting ${PART} as ext4"  
  mkfs.ext4 -F "$PART" >/dev/null  
fi  
  
# ==================================================================  
# 5. Mount by UUID at /mnt/dizerdata + fstab  
# ==================================================================  
UUID="$(blkid -o value -s UUID "$PART")"  
[ -n "$UUID" ] || die "Could not read UUID of ${PART}."  
  
mkdir -p "$DATA_MOUNT"  
if ! mountpoint -q "$DATA_MOUNT"; then  
  mount "$PART" "$DATA_MOUNT"  
  MOUNTED="$DATA_MOUNT"  
fi  
ok "Mounted ${PART} at ${DATA_MOUNT} (UUID ${UUID})"  
  
grep -q "$UUID" "$FSTAB" 2>/dev/null || \  
  printf 'UUID=%s  %s  ext4  defaults,noatime  0  2\n' "$UUID" "$DATA_MOUNT" >> "$FSTAB"  
ok "fstab entry present for UUID ${UUID}"  
  
mkdir -p "$DATA_DIR"  
chown -R "${INSTALLER_USER}:${INSTALLER_USER}" "$DATA_DIR" 2>/dev/null || true  
  
# ==================================================================  
# 6. Collect API keys + write env file  
# ==================================================================  
ok "Collecting API keys (input hidden)"  
read -r -s -p "GEMINI_API_KEY: " GEMINI_API_KEY < /dev/tty; echo ""  
read -r -s -p "OPENROUTER_API_KEY_CODER: " OR_CODER < /dev/tty; echo ""  
read -r -s -p "OPENROUTER_API_KEY_JUDGE (optional, Enter to reuse coder key): " OR_JUDGE < /dev/tty; echo ""  
read -r -s -p "GROQ_API_KEY: " GROQ_KEY < /dev/tty; echo ""  
read -r -s -p "WEBUI_ADMIN_PASSWORD: " ADMIN_PW < /dev/tty; echo ""  
  
[ -n "$GEMINI_API_KEY" ] && [ -n "$OR_CODER" ] && [ -n "$GROQ_KEY" ] && [ -n "$ADMIN_PW" ] \  
  || die "GEMINI_API_KEY, OPENROUTER_API_KEY_CODER, GROQ_API_KEY and WEBUI_ADMIN_PASSWORD are required."  
OR_JUDGE="${OR_JUDGE:-$OR_CODER}"  
  
cat > "$ENV_FILE" <<EOF  
GEMINI_API_KEY=${GEMINI_API_KEY}  
OPENROUTER_API_KEY_CODER=${OR_CODER}  
OPENROUTER_API_KEY_JUDGE=${OR_JUDGE}  
GROQ_API_KEY=${GROQ_KEY}  
WEBUI_ADMIN_PASSWORD=${ADMIN_PW}  
DIZER_DATA_DIR=${DATA_DIR}  
PORT=${PORT}  
EOF  
chmod 600 "$ENV_FILE"  
ok "Env written to ${ENV_FILE}"  
  
# ==================================================================  
# 7. Clone repo + stamp VERSION (sha  timestamp  repo) + freshness  
# ==================================================================  
ok "Cloning ${REPO}"  
rm -rf "$APP_DIR"  
git clone --branch "$BRANCH" "$REPO" "$APP_DIR"  
  
printf '%s %s %s\n' \  
  "$(cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo unknown)" \  
  "$(date -u +%Y-%m-%dT%H:%MZ)" \  
  "$REPO" > "$APP_DIR/VERSION"  
ok "VERSION stamped: $(cat "$APP_DIR/VERSION")"  
  
LOCAL_FULL="$(cd "$APP_DIR" && git rev-parse HEAD 2>/dev/null || echo "")"  
REMOTE_FULL="$(git ls-remote "$REPO" "refs/heads/${BRANCH}" 2>/dev/null | awk '{print $1}')" || true  
if [ -z "$REMOTE_FULL" ]; then  
  warn "Could not reach GitHub to verify latest commit; skipping freshness check."  
elif [ "$REMOTE_FULL" = "$LOCAL_FULL" ]; then  
  ok "Installed commit ${LOCAL_FULL:0:7} is the latest on ${BRANCH}."  
else  
  warn "Installed commit ${LOCAL_FULL:0:7} is NOT the latest. Remote ${BRANCH} HEAD is ${REMOTE_FULL:0:7}."  
fi  
  
[ -f "$APP_DIR/$ENTRYPOINT" ] || die "Entrypoint ${ENTRYPOINT} not found in repo."  
if [ ! -f "$APP_DIR/static/dizercore.png" ]; then  
  warn "static/dizercore.png not found; dashboard logo and favicon will be blank."  
fi  
  
# ==================================================================  
# 8. Python venv + dependencies  
# ==================================================================  
ok "Creating venv + installing deps"  
python3 -m venv "$APP_DIR/venv"  
"$APP_DIR/venv/bin/pip" install --upgrade pip >/dev/null  
if [ -f "$APP_DIR/requirements.txt" ]; then  
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"  
else  
  "$APP_DIR/venv/bin/pip" install fastapi uvicorn httpx google-genai python-multipart  
fi  
chown -R "${INSTALLER_USER}:${INSTALLER_USER}" "$APP_DIR" 2>/dev/null || true  
  
# ==================================================================  
# 9. systemd service  
# ==================================================================  
ok "Installing systemd service ${SERVICE_NAME}"  
{  
  printf '[Unit]\n'  
  printf 'Description=%s\n' "$APP_NAME"  
  printf 'RequiresMountsFor=%s\n' "$DATA_MOUNT"  
  printf 'After=network-online.target\n'  
  printf 'Wants=network-online.target\n'  
  printf '\n'  
  printf '[Service]\n'  
  printf 'User=%s\n' "$INSTALLER_USER"  
  printf 'Group=%s\n' "$INSTALLER_USER"  
  printf 'WorkingDirectory=%s\n' "$APP_DIR"  
  printf 'EnvironmentFile=%s\n' "$ENV_FILE"  
  printf 'ExecStart=%s/venv/bin/python3 %s/%s\n' "$APP_DIR" "$APP_DIR" "$ENTRYPOINT"  
  printf 'Restart=on-failure\n'  
  printf 'RestartSec=3\n'  
  printf 'StandardOutput=journal\n'  
  printf 'StandardError=journal\n'  
  printf '\n'  
  printf '[Install]\n'  
  printf 'WantedBy=multi-user.target\n'  
} | tee "$SERVICE" >/dev/null  
  
systemctl daemon-reload  
systemctl enable "$SERVICE_NAME"  
systemctl restart "$SERVICE_NAME"  
  
# ==================================================================  
# 10. Print the URL  
# ==================================================================  
IP="$(hostname -I | awk '{print $1}')"  
echo ""  
banner "${APP_NAME} is running"  
echo " Open:       http://${IP}:${PORT}/"  
echo " Live logs:  journalctl -u ${SERVICE_NAME} -f"  
echo "============================================================"
