#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install.sh — one-shot installer for Raspberry Pi 5 (headless).  
# Auto-detects plugged-in SSDs (excludes the SD card / boot disk), lets  
# the user pick the target, applies the UAS quirk hotfix automatically,  
# formats ext4 ONLY if needed (with an explicit erase warning), mounts  
# by UUID at /mnt/dizerdata, writes the env file (incl. optional  
# dedicated OpenRouter JUDGE key), installs the systemd service.  
#  
# Safe to run piped:  curl -fsSL <raw-url> | sudo bash  
# (every read pulls from /dev/tty, not stdin — piping can't feed prompts)  
# ==================================================================  
set -Eeuo pipefail  
  
REPO="https://github.com/vekzla/DizerCore-AI.git"  
BRANCH="main"  
APP_NAME="DizerCoreAI"  
ENTRYPOINT="dizercoreai.py"  
SERVICE_NAME="dizercore"  
APP_DIR="/opt/DizerCoreAI"  
DATA_MOUNT="/mnt/dizerdata"  
PORT="8000"  
  
MOUNTED=false  
  
# ---------- pretty output ----------  
banner(){ echo; echo "============================================================"; echo " $*"; echo "============================================================"; }  
ok(){     echo "==> $*"; }  
warn(){   echo "!!  $*"; }  
die(){    echo "ERROR: $*" >&2; exit 1; }  
  
cleanup_on_err(){  
  if [ "$MOUNTED" = true ]; then  
    warn "Install failed; unmounting ${DATA_MOUNT}."  
    sudo umount -l "$DATA_MOUNT" 2>/dev/null || true  
  fi  
}  
trap cleanup_on_err ERR  
  
# ---------- helpers ----------  
root_dev(){ findmnt -no SOURCE /; }                       # e.g. /dev/mmcblk0p2  
disk_of(){ lsblk -no PKNAME "$1" 2>/dev/null || true; }   # parent disk of a partition  
is_removable(){ [[ "$(cat "/sys/block/$1/removable" 2>/dev/null || echo 0)" == "1" ]]; }  
  
usb_storage_disk(){  
  local d="$1" p  
  p="$(readlink -f "/sys/block/$d" 2>/dev/null || true)"  
  [[ "$p" == *usb* ]] && return 0  
  command -v udevadm >/dev/null 2>&1 && \  
    udevadm info --query=property --name="$d" 2>/dev/null | grep -q 'ID_BUS=usb' && return 0  
  [[ "$(cat "/sys/block/$d/device/model" 2>/dev/null)" =~ [Uu][Ss][Bb] ]] && return 0  
  return 1  
}  
  
# ==================================================================  
# 0. Root check  
# ==================================================================  
[ "$EUID" -eq 0 ] || die "Run as root: curl ... | sudo bash   (sudo on bash, not curl)"  
  
banner "DizerCore-AI installer"  
echo " Repo:      $REPO ($BRANCH)"  
echo " App dir:   $APP_DIR"  
echo " Data dir:  $DATA_MOUNT"  
echo " Service:   $SERVICE_NAME (port $PORT)"  
  
# ==================================================================  
# 1. Remove any previous install (clean slate)  
# ==================================================================  
ok "Removing any previous install"  
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true  
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true  
sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"  
sudo systemctl daemon-reload  
sudo rm -rf "$APP_DIR"  
  
# ==================================================================  
# 2. Pick the target SSD  
# ==================================================================  
ROOT_DISK="$(disk_of "$(root_dev)")"  
ok "Boot disk detected: ${ROOT_DISK:-unknown} (excluded from choices)"  
  
mapfile -t DISKS < <(  
  lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print $1}' | while read -r d; do  
    [ "$d" = "$ROOT_DISK" ] && continue  
    case "$d" in loop*|ram*|zram*|mmcblk*) continue ;; esac  
    echo "$d"  
  done  
)  
  
[ "${#DISKS[@]}" -gt 0 ] || die "No non-boot disks found. Plug in the SSD and re-run."  
  
echo ""  
echo "Available disks:"  
for i in "${!DISKS[@]}"; do  
  d="${DISKS[$i]}"  
  size="$(lsblk -dn -o SIZE "/dev/$d" 2>/dev/null || echo '?')"  
  model="$(lsblk -dn -o MODEL "/dev/$d" 2>/dev/null | xargs || true)"  
  flags=""  
  is_removable "$d" && flags="$flags removable"  
  usb_storage_disk "$d" && flags="$flags usb"  
  printf "  [%d] /dev/%-8s %-6s %s %s\n" "$i" "$d" "$size" "${model:-unknown}" "$flags"  
done  
  
echo ""  
# </dev/tty: prompt reads the real terminal even when the script itself is piped in.  
read -r -p "Pick disk number for DizerCore data [0]: " PICK < /dev/tty  
PICK="${PICK:-0}"  
[[ "$PICK" =~ ^[0-9]+$ ]] && [ "$PICK" -lt "${#DISKS[@]}" ] || die "Invalid choice."  
DISK="${DISKS[$PICK]}"  
DEV="/dev/$DISK"  
ok "Selected: $DEV ($(lsblk -dn -o MODEL "$DEV" 2>/dev/null | xargs || echo 'unknown model'))"  
  
# ==================================================================  
# 3. UAS quirk hotfix (fix common USB-SATA bridge resets on Pi)  
# ==================================================================  
if usb_storage_disk "$DISK"; then  
  BP="$(readlink -f "/sys/block/$DISK/device" 2>/dev/null || true)"  
  VID="$(cat "$BP/../idVendor" 2>/dev/null || true)"  
  PID="$(cat "$BP/../idProduct" 2>/dev/null || true)"  
  if [ -n "$VID" ] && [ -n "$PID" ]; then  
    QUIRK="${VID}:${PID}:u"  
    CMDLINE="/boot/firmware/cmdline.txt"  
    [ -f "$CMDLINE" ] || CMDLINE="/boot/cmdline.txt"  
    if [ -f "$CMDLINE" ] && ! grep -q "usb-storage.quirks=$QUIRK" "$CMDLINE"; then  
      warn "Applying UAS quirk $QUIRK to $CMDLINE (reboot required to take effect)"  
      sudo sed -i "s/$/ usb-storage.quirks=$QUIRK/" "$CMDLINE"  
    fi  
  fi  
fi  
  
# ==================================================================  
# 4. Format ext4 ONLY if needed (explicit erase warning)  
# ==================================================================  
if [ -z "$(lsblk -no FSTYPE "$DEV" 2>/dev/null | head -n1)" ]; then  
  warn "NO FILESYSTEM on $DEV — it will be ERASED and formatted ext4."  
  read -r -p "Type ERASE to confirm: " CONF < /dev/tty  
  [ "$CONF" = "ERASE" ] || die "Aborted."  
  sudo wipefs -a "$DEV"  
  sudo mkfs.ext4 -F -L dizerdata "$DEV"  
  FS_SRC="$DEV"  
else  
  ok "Existing filesystem on $DEV — leaving it alone."  
  FS_SRC="$DEV"  
  # If the disk has partitions, mount the first one instead.  
  FIRSTPART="$(lsblk -nro NAME "$DEV" | sed -n '2p' || true)"  
  [ -n "$FIRSTPART" ] && FS_SRC="/dev/$FIRSTPART"  
fi  
  
# ==================================================================  
# 5. Mount by UUID  
# ==================================================================  
sudo mkdir -p "$DATA_MOUNT"  
UUID="$(sudo blkid -s UUID -o value "$FS_SRC" 2>/dev/null || true)"  
[ -n "$UUID" ] || die "Could not read UUID of $FS_SRC"  
  
grep -q "$UUID" /etc/fstab || \  
  echo "UUID=$UUID $DATA_MOUNT ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab >/dev/null  
  
sudo umount "$DATA_MOUNT" 2>/dev/null || true  
sudo mount -a  
MOUNTED=true  
ok "Mounted $FS_SRC at $DATA_MOUNT"  
  
# ==================================================================  
# 6. Clone repo + stamp version + freshness check  
# ==================================================================  
ok "Cloning ${REPO}"  
git clone --branch "$BRANCH" "$REPO" "$APP_DIR"  
  
ok "Stamping version"  
# Single line: "SHA  TIMESTAMP  REPO" — version.py's get_version_info() parses it.  
printf '%s %s %s\n' "$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)" "$(date -u +%Y-%m-%dT%H:%MZ)" "$REPO" > "$APP_DIR/VERSION"  
  
ok "Checking whether the install is on the latest commit"  
LOCAL_FULL="$( git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo "" )"  
LOCAL_SHORT="$( git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown" )"  
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
# 7. Python deps  
# ==================================================================  
ok "Installing Python dependencies"  
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true  
python3 -m pip install --break-system-packages -r "$APP_DIR/requirements.txt" 2>/dev/null \  
  || python3 -m pip install --break-system-packages fastapi uvicorn httpx google-genai python-multipart  
  
# ==================================================================  
# 8. Secrets + env file  
# ==================================================================  
ENV_FILE="${DATA_MOUNT}/dizercore.env"  
  
echo ""  
banner "API keys (input hidden — paste then press Enter)"  
read -r -s -p "GEMINI_API_KEY: "              GEMINI_API_KEY              < /dev/tty; echo ""  
read -r -s -p "OPENROUTER_API_KEY_CODER: "    OPENROUTER_API_KEY_CODER    < /dev/tty; echo ""  
read -r -s -p "OPENROUTER_API_KEY_JUDGE (optional, Enter to reuse coder key): " OPENROUTER_API_KEY_JUDGE < /dev/tty; echo ""  
read -r -s -p "GROQ_API_KEY: "                GROQ_API_KEY                < /dev/tty; echo ""  
read -r -s -p "WEBUI_ADMIN_PASSWORD: "        WEBUI_ADMIN_PASSWORD        < /dev/tty; echo ""  
  
[ -n "$GEMINI_API_KEY" ]           || die "GEMINI_API_KEY is required."  
[ -n "$OPENROUTER_API_KEY_CODER" ] || die "OPENROUTER_API_KEY_CODER is required."  
[ -n "$GROQ_API_KEY" ]             || die "GROQ_API_KEY is required."  
[ -n "$WEBUI_ADMIN_PASSWORD" ]     || die "WEBUI_ADMIN_PASSWORD is required."  
[ -n "$OPENROUTER_API_KEY_JUDGE" ] || OPENROUTER_API_KEY_JUDGE="$OPENROUTER_API_KEY_CODER"  
  
cat > "$ENV_FILE" <<EOF  
DIZER_DATA_DIR=${DATA_MOUNT}/dizercore  
GEMINI_API_KEY=${GEMINI_API_KEY}  
OPENROUTER_API_KEY_CODER=${OPENROUTER_API_KEY_CODER}  
OPENROUTER_API_KEY_JUDGE=${OPENROUTER_API_KEY_JUDGE}  
GROQ_API_KEY=${GROQ_API_KEY}  
WEBUI_ADMIN_PASSWORD=${WEBUI_ADMIN_PASSWORD}  
PORT=${PORT}  
EOF  
chmod 600 "$ENV_FILE"  
mkdir -p "${DATA_MOUNT}/dizercore"  
ok "Wrote env file: $ENV_FILE"  
  
# ==================================================================  
# 9. systemd service  
# ==================================================================  
SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"  
ok "Writing systemd unit: $SERVICE"  
{  
  printf '[Unit]\n'  
  printf 'Description=DizerCoreAI\n'  
  printf 'After=network-online.target\n'  
  printf 'Wants=network-online.target\n'  
  printf 'RequiresMountsFor=%s\n' "$DATA_MOUNT"  
  printf '\n'  
  printf '[Service]\n'  
  printf 'Type=simple\n'  
  printf 'User=%s\n' "${SUDO_USER:-root}"  
  printf 'WorkingDirectory=%s\n' "$APP_DIR"  
  printf 'EnvironmentFile=%s\n' "$ENV_FILE"  
  printf 'ExecStart=/usr/bin/python3 %s\n' "$APP_DIR/$ENTRYPOINT"  
  printf 'Restart=on-failure\n'  
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
