#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install.sh — one-shot installer for Raspberry Pi 5 (headless).  
# Auto-detects plugged-in SSDs (excludes the SD card / boot disk), lets  
# the user pick the target, applies the UAS quirk hotfix automatically,  
# then ALWAYS wipes the picked disk clean (new GPT label + single ext4  
# partition) after a typed ERASE confirmation. Mounts by UUID at  
# /mnt/dizerdata, writes the env file (or restores the SD-card backup),  
# installs the systemd unit, and starts the service.  
# ==================================================================  
  
set -e  
set -u  
set -o pipefail  
  
REPO="https://github.com/vekzla/DizerCore-AI.git"  
APP_NAME="DizerCoreAI"  
SERVICE_NAME="dizercore"  
APP_DIR="$HOME/DizerCore-AI"  
MOUNT="/mnt/dizerdata"  
APP_DATA="$MOUNT/dizercore"  
ENV_FILE="$APP_DATA/dizercore.env"  
ENV_BAK="$HOME/dizercore.env.bak"   # lives on the SD card — survives SSD wipes  
PORT="8000"  
  
say()  { printf '%s\n' "$*"; }  
ok()   { printf 'OK  %s\n' "$*"; }  
die()  { printf 'XX  %s\n' "$*" >&2; exit 1; }  
need() { command -v "$1" >/dev/null 2>&1 || die "missing: $1"; }  
banner() {  
  echo "============================================================"  
  echo " $1"  
  echo "============================================================"  
}  
  
banner "$APP_NAME install"  
  
# ==================================================================  
# 1. If an install already exists, back up the env file before we wipe  
# ==================================================================  
if [ -f "$ENV_FILE" ] && [ ! -f "$ENV_BAK" ]; then  
  echo ""  
  read -r -p "Existing env file found on SSD. Back it up to the SD card? [y/N] " a  
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then  
    cp "$ENV_FILE" "$ENV_BAK"  
    chmod 600 "$ENV_BAK"  
    ok "Backed up keys to $ENV_BAK"  
  fi  
fi  
if [ -d "$APP_DIR" ]; then  
  echo ""  
  read -r -p "Existing install found at $APP_DIR — remove and reinstall? [y/N] " a  
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then  
    rm -rf "$APP_DIR"  
    ok "Removed $APP_DIR"  
  fi  
fi  
  
# ==================================================================  
# 2. Pick the SSD  
# ==================================================================  
echo ""  
say "Scanning disks (SD card / boot disk excluded)..."  
  
BOOT_SRC="$(findmnt -n -o SOURCE / 2>/dev/null || true)"  
BOOT_DISK=""  
if [ -n "$BOOT_SRC" ]; then  
  BOOT_DISK="$(lsblk -no PKNAME "$BOOT_SRC" 2>/dev/null | head -n1 || true)"  
  [ -n "$BOOT_DISK" ] && BOOT_DISK="/dev/$BOOT_DISK"  
fi  
  
mapfile -t CANDIDATES < <(lsblk -dpno NAME,SIZE,MODEL,TRAN \  
  | awk -v boot="$BOOT_DISK" '$1 != boot && $1 !~ /mmcblk/ {print $0}')  
  
[ "${#CANDIDATES[@]}" -gt 0 ] || die "no non-SD disks found — plug in the SSD"  
  
echo ""  
say "Available disks:"  
i=0  
for line in "${CANDIDATES[@]}"; do  
  i=$((i+1))  
  printf '  %d) %s\n' "$i" "$line"  
done  
  
if [ "$i" -eq 1 ]; then  
  PICK=1  
else  
  read -r -p "Pick a disk number to wipe and use [1-$i]: " PICK  
fi  
  
case "$PICK" in ''|*[!0-9]*) die "invalid choice" ;; esac  
[ "$PICK" -ge 1 ] && [ "$PICK" -le "$i" ] || die "invalid choice"  
  
DISK="$(printf '%s\n' "${CANDIDATES[$((PICK-1))]}" | awk '{print $1}')"  
[ -b "$DISK" ] || die "not a block device: $DISK"  
say "Selected: $DISK"  
  
# ==================================================================  
# 3. UAS quirk hotfix (Pi 5 USB-attached SSD flakiness)  
# ==================================================================  
VIDPID="$(lsblk -no NAME "$DISK" | head -n1 >/dev/null; udevadm info --query=property --name="$DISK" 2>/dev/null | awk -F= '/ID_USB_DRIVER|ID_MODEL_ID|ID_VENDOR_ID/{print $0}' | tr '\n' ' ' || true)"  
# Build vendor:product id for usb-storage quirks  
VID="$(udevadm info --query=property --name="$DISK" 2>/dev/null | awk -F= '$1=="ID_VENDOR_ID"{print $2}')"  
PID="$(udevadm info --query=property --name="$DISK" 2>/dev/null | awk -F= '$1=="ID_MODEL_ID"{print $2}')"  
if [ -n "$VID" ] && [ -n "$PID" ]; then  
  QUIRK="$VID:$PID:u"  
  CMDLINE=/boot/firmware/cmdline.txt  
  [ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt  
  if [ -f "$CMDLINE" ] && ! grep -q "usb-storage.quirks=$QUIRK" "$CMDLINE"; then  
    sudo sed -i "s/$/ usb-storage.quirks=$QUIRK/" "$CMDLINE"  
    ok "Added UAS quirk usb-storage.quirks=$QUIRK to $CMDLINE (takes effect after reboot)"  
  fi  
fi  
  
# ==================================================================  
# 4. Wipe the disk — typed confirmation required  
# ==================================================================  
echo ""  
say "!!! $DISK WILL BE COMPLETELY ERASED — new GPT label + one ext4 partition !!!"  
read -r -p "Type ERASE to continue: " CONFIRM  
[ "$CONFIRM" = "ERASE" ] || die "aborted — disk untouched"  
  
need lsblk; need sgdisk; need mkfs.ext4; need git; need curl  
  
sudo umount "${DISK}"* 2>/dev/null || true  
sudo sgdisk --zap-all "$DISK" >/dev/null  
sudo sgdisk -n1=0:0:0 -t1:8300 "$DISK" >/dev/null  
sudo partprobe "$DISK" || true  
sleep 2  
  
PART="$(lsblk -rno NAME "$DISK" | awk 'NR==2{print "/dev/"$1}')"  
[ -b "$PART" ] || PART="${DISK}1"  
[ -b "$PART" ] || die "partition not created on $DISK"  
  
sudo mkfs.ext4 -F -L dizerdata "$PART" >/dev/null  
UUID="$(blkid -s UUID -o value "$PART")"  
[ -n "$UUID" ] || die "no UUID on $PART"  
ok "Formatted $PART (UUID $UUID)"  
  
# ==================================================================  
# 5. Mount by UUID  
# ==================================================================  
sudo mkdir -p "$MOUNT"  
grep -q "$UUID" /etc/fstab || \  
  echo "UUID=$UUID $MOUNT ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab >/dev/null  
sudo mount -a  
mountpoint -q "$MOUNT" || die "mount failed"  
sudo mkdir -p "$APP_DATA"  
sudo chown -R "$USER":"$USER" "$APP_DATA"  
ok "Mounted at $MOUNT"  
  
# ==================================================================  
# 6. Clone + venv + deps  
# ==================================================================  
if [ ! -d "$APP_DIR" ]; then  
  git clone "$REPO" "$APP_DIR"  
fi  
cd "$APP_DIR"  
ok "Cloned $REPO"  
  
sudo apt-get update -qq  
sudo apt-get install -y -qq python3-venv python3-pip >/dev/null  
[ -d venv ] || python3 -m venv venv  
./venv/bin/pip install -q --upgrade pip  
./venv/bin/pip install -q -r requirements.txt  
ok "Python venv + requirements installed"  
  
# ==================================================================  
# 7. Env file — restore from SD backup or prompt for keys  
# ==================================================================  
mkdir -p "$APP_DATA"  
SKIP_KEYS=""  
if [ -f "$ENV_BAK" ]; then  
  echo ""  
  read -r -p "Saved API keys found at $ENV_BAK (SD card). Reuse them? [y/N] " a  
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then  
    cp "$ENV_BAK" "$ENV_FILE"  
    chmod 600 "$ENV_FILE"  
    ok "Restored keys to $ENV_FILE"  
    SKIP_KEYS=1  
  fi  
fi  
  
if [ -z "$SKIP_KEYS" ]; then  
  echo ""  
  say "Enter your API keys (input is hidden; judge key optional — press Enter to skip):"  
  read -r -s -p "GEMINI_API_KEY: " GEMINI; echo ""  
  read -r -s -p "OPENROUTER_API_KEY_CODER: " CODER; echo ""  
  read -r -s -p "GROQ_API_KEY: " GROQ; echo ""  
  read -r -s -p "OPENROUTER_API_KEY_JUDGE (optional): " JUDGE; echo ""  
  read -r -s -p "WEBUI_ADMIN_PASSWORD: " ADMIN; echo ""  
  JUDGE="${JUDGE:-$CODER}"  
  cat > "$ENV_FILE" <<EOF  
DIZER_DATA_DIR=$APP_DATA  
GEMINI_API_KEY=$GEMINI  
OPENROUTER_API_KEY_CODER=$CODER  
OPENROUTER_API_KEY_JUDGE=$JUDGE  
GROQ_API_KEY=$GROQ  
WEBUI_ADMIN_PASSWORD=$ADMIN  
PORT=$PORT  
EOF  
  chmod 600 "$ENV_FILE"  
  # Keep a copy on the SD card so the next SSD wipe can restore it  
  cp "$ENV_FILE" "$ENV_BAK"  
  chmod 600 "$ENV_BAK"  
  ok "Wrote $ENV_FILE (backup saved to $ENV_BAK on SD card)"  
fi  
  
# ==================================================================  
# 8. Stamp VERSION  
# ==================================================================  
SHA="$(cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"  
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"  
echo "$SHA $STAMP $REPO" > "$APP_DIR/VERSION"  
ok "Version stamped: $SHA"  
  
# ==================================================================  
# 9. systemd unit  
# ==================================================================  
SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"  
sudo tee "$SERVICE" >/dev/null <<EOF  
[Unit]  
Description=$APP_NAME  
After=network-online.target  
Wants=network-online.target  
  
[Service]  
Type=simple  
User=$USER  
WorkingDirectory=$APP_DIR  
EnvironmentFile=$ENV_FILE  
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/dizercoreai.py  
Restart=always  
RestartSec=3  
StandardOutput=journal  
StandardError=journal  
  
[Install]  
WantedBy=multi-user.target  
EOF  
  
sudo systemctl daemon-reload  
sudo systemctl enable "$SERVICE_NAME"  
sudo systemctl restart "$SERVICE_NAME"  
  
# ==================================================================  
# 10. Print the URL  
# ==================================================================  
IP="$(hostname -I | awk '{print $1}')"  
echo ""  
banner "$APP_NAME is running"  
echo " Open:       http://${IP}:${PORT}/"  
echo " Live logs:  journalctl -u ${SERVICE_NAME} -f"  
echo "============================================================"
