#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install-executor.sh — installer for the DizerCore-AI.Build-Agent pi  
# (the remote build executor). Normally reached via install.sh's role  
# picker, but also runnable directly:  
#   curl -fsSL ".../install-executor.sh?nocache=$(date +%s)" | tr -d '\r' | bash  
#  
#   1. Asks for the Code-Agent's IP (the pi that will SSH in).  
#   2. Detects NVMe/SSD (excludes SD card / boot disk), user picks,  
#      typed ERASE -> GPT + ext4 labelled "DizerBuild".  
#   3. Mounts by UUID at /mnt/build (nofail + x-systemd.device-timeout).  
#   4. Creates "dizerbuild" user + ~/.ssh/authorized_keys.  
#   5. Installs build tooling + sandbox deps (bwrap, prlimit) and  
#      pulls the executor model via Ollama.  
#   6. Creates /mnt/build/jobs/ + /mnt/build/repo.git (bare).  
#   7. Prints THIS machine's IP — enter it into install.sh section 9  
#      on the Code-Agent.  
#  
# Command contract (Code-Agent side, pipeline._remote_build):  
#   rsync -az -e "ssh -i KEY" <pkgdir>/  dizerbuild@IP:/mnt/build/jobs/<id>/  
#   ssh  -i KEY dizerbuild@IP prlimit --as=<MB>m --cpu=<S> \  
#        bwrap --unshare-all --bind /mnt/build/jobs/<id> /work \  
#        --chdir /work --dev /dev --proc /proc -- /bin/sh -lc "<cmd>"  
# ==================================================================  
set -Eeuo pipefail  
  
BUILD_USER="dizerbuild"  
BUILD_ROOT="/mnt/build"  
NVME_LABEL="DizerBuild"  
USER_HOME="/home/${BUILD_USER}"  
  
# Executor model pulled via Ollama — override with BUILD_MODEL env.  
BUILD_MODEL="${BUILD_MODEL:-qwen2.5-coder:7b}"  
  
CODE_IP=""  
EXEC_IP=""  
  
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
  
ask_ip() {  
  # ask_ip <prompt> -> sets REPLY_IP to a validated IPv4 string  
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
  
# ------------------------------------------------------------------  
# pick_build_disk / wipe_build_disk — build NVMe, always wiped.  
# ------------------------------------------------------------------  
pick_build_disk() {  
  local root_src root_disk  
  root_src="$(findmnt -n -o SOURCE / 2>/dev/null || true)"  
  root_disk="$(basename "$(lsblk -n -o PKNAME "$root_src" 2>/dev/null || true)")"  
  [ -z "$root_disk" ] && root_disk="$(basename "$root_src" | sed 's/p*[0-9]*$//')"  
  
  mapfile -t ROWS < <(lsblk -lnpo NAME,TYPE,FSTYPE,SIZE,MOUNTPOINT 2>/dev/null)  
  
  CANDS=()  
  local dev type fstype size mnt  
  while read -r dev type fstype size mnt; do  
    [ "$type" = "disk" ] || continue  
    [ "$(basename "$dev")" = "$root_disk" ] && continue  
    case "$dev" in  
      /dev/mmcblk*|/dev/loop*|/dev/zram*|/dev/ram*) continue ;;  
    esac  
    CANDS+=("$dev|$size|${fstype:-none}")  
  done <<<"$(printf '%s\n' "${ROWS[@]}")"  
  
  [ "${#CANDS[@]}" -gt 0 ] || die "No usable NVMe/SSD found (boot disk and SD card excluded)."  
  
  echo ""  
  echo "Detected candidate build disks:"  
  local i  
  for i in "${!CANDS[@]}"; do  
    IFS='|' read -r cdev csize cfs <<<"${CANDS[$i]}"  
    echo "  [$((i + 1))]  ${cdev}  (${csize}, filesystem: ${cfs})"  
  done  
  echo ""  
  
  local choice=""  
  while true; do  
    read -r -p "Which disk is the Build-Agent NVMe? [1-${#CANDS[@]}] " choice </dev/tty || true  
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#CANDS[@]}" ]; then  
      IFS='|' read -r BLK_DISK _sz _fs <<<"${CANDS[$((choice - 1))]}"  
      return 0  
    fi  
    warn "Enter a number between 1 and ${#CANDS[@]}."  
  done  
}  
  
wipe_build_disk() {  
  echo ""  
  warn "INSTALL = FULL WIPE. EVERYTHING on ${BLK_DISK} will be destroyed:"  
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT "$BLK_DISK" || true  
  echo ""  
  local reply=""  
  read -r -p "Type ERASE to wipe ${BLK_DISK} clean: " reply </dev/tty || true  
  [ "$reply" = "ERASE" ] || { echo "Aborted."; exit 0; }  
  
  ok "Unmounting everything on ${BLK_DISK}"  
  sudo umount "${BLK_DISK}"* 2>/dev/null || true  
  
  ok "Wiping ${BLK_DISK} (new GPT label + single ext4 partition)"  
  sudo wipefs -a "$BLK_DISK"  
  sudo parted -s "$BLK_DISK" mklabel gpt  
  sudo parted -s "$BLK_DISK" mkpart primary ext4 0% 100%  
  sudo partprobe "$BLK_DISK" || true  
  sleep 2  
  
  if [[ "$BLK_DISK" =~ (nvme|mmcblk|loop) ]]; then  
    BLK_PART="${BLK_DISK}p1"  
  else  
    BLK_PART="${BLK_DISK}1"  
  fi  
  [ -b "$BLK_PART" ] || die "Expected new partition ${BLK_PART} not found after wipe."  
  
  ok "Formatting ${BLK_PART} as ext4 (label ${NVME_LABEL})"  
  sudo mkfs.ext4 -F -L "$NVME_LABEL" "$BLK_PART"  
}  
  
# ==================================================================  
# 0. Banner + IPs of both pis  
# ==================================================================  
banner "DizerCore-AI Build-Agent installer"  
require_tty  
  
echo ""  
echo "This pi is the Build-Agent. The other pi runs the Code-Agent"  
echo "(the DizerCore pipeline that SSHes in to run builds)."  
ask_ip "Code-Agent IP address"; CODE_IP="$REPLY_IP"  
EXEC_GUESS="$(hostname -I 2>/dev/null | awk '{print $1}')"  
ask_ip "This Build-Agent's IP" "$EXEC_GUESS"; EXEC_IP="$REPLY_IP"  
  
PREV=0  
id "$BUILD_USER" &>/dev/null && PREV=1  
[ -d "$BUILD_ROOT/jobs" ] && PREV=1  
if [ "$PREV" -eq 1 ]; then  
  echo ""  
  warn "A previous executor install was detected (user '${BUILD_USER}' or ${BUILD_ROOT} exists)."  
  echo "This will wipe the picked disk (ERASE), reset ${USER_HOME}/.ssh,"  
  echo "and re-create ${BUILD_ROOT}. Re-run is safe but destructive."  
  if ! confirm "Re-install the Build-Agent?"; then  
    echo "Aborted."  
    exit 0  
  fi  
fi  
  
# ==================================================================  
# 1. System deps + executor model  
# ==================================================================  
ok "Installing system dependencies"  
sudo apt-get update -y  
sudo apt-get install -y git rsync build-essential cmake python3 bubblewrap util-linux parted curl openssh-server  
  
if ! command -v ollama >/dev/null 2>&1; then  
  ok "Installing Ollama"  
  curl -fsSL https://ollama.com/install.sh | sh  
fi  
ok "Pulling executor model ${BUILD_MODEL}"  
ollama pull "$BUILD_MODEL"  
  
# ==================================================================  
# 2. NVMe — pick, ERASE-wipe, format as DizerBuild  
# ==================================================================  
BLK_DISK=""  
BLK_PART=""  
pick_build_disk  
ok "Using ${BLK_DISK} for the build volume"  
wipe_build_disk  
ok "Wipe complete; using ${BLK_PART}"  
  
# ==================================================================  
# 3. Mount by UUID at BUILD_ROOT  
# ==================================================================  
ok "Mounting the build volume at ${BUILD_ROOT}"  
NEW_UUID="$(sudo blkid -s UUID -o value "$BLK_PART")"  
[ -n "$NEW_UUID" ] || die "Could not read UUID of ${BLK_PART}"  
  
sudo mkdir -p "$BUILD_ROOT"  
sudo sed -i "\|${BUILD_ROOT}|d" /etc/fstab  
echo "UUID=${NEW_UUID}  ${BUILD_ROOT}  ext4  defaults,nofail,x-systemd.device-timeout=10  0  2" | sudo tee -a /etc/fstab >/dev/null  
sudo systemctl daemon-reload  
sudo mount -a  
findmnt "$BUILD_ROOT" >/dev/null || die "Build volume failed to mount at ${BUILD_ROOT}"  
  
# ==================================================================  
# 4. dizerbuild service user + ~/.ssh (keyed from the Code-Agent)  
# ==================================================================  
ok "Creating '${BUILD_USER}' service user"  
if ! id "$BUILD_USER" &>/dev/null; then  
  sudo useradd -m -s /bin/bash "$BUILD_USER"  
fi  
sudo mkdir -p "${USER_HOME}/.ssh"  
sudo touch "${USER_HOME}/.ssh/authorized_keys"  
sudo chmod 700 "${USER_HOME}/.ssh"  
sudo chmod 600 "${USER_HOME}/.ssh/authorized_keys"  
sudo chown -R "${BUILD_USER}:${BUILD_USER}" "${USER_HOME}/.ssh"  
sudo systemctl enable --now ssh 2>/dev/null || true  
  
# ==================================================================  
# 5. Build workspace layout  
# ==================================================================  
ok "Creating build layout under ${BUILD_ROOT}"  
sudo mkdir -p "${BUILD_ROOT}/jobs"  
sudo mkdir -p "${BUILD_ROOT}/repo.git"  
if [ ! -f "${BUILD_ROOT}/repo.git/HEAD" ]; then  
  sudo git init --bare "${BUILD_ROOT}/repo.git"  
fi  
sudo chown -R "${BUILD_USER}:${BUILD_USER}" "$BUILD_ROOT"  
sudo chmod 755 "$BUILD_ROOT"  
  
# ==================================================================  
# 6. Done  
# ==================================================================  
echo ""  
banner "DizerCore-AI Build-Agent ready"  
echo " This pi:      ${BUILD_USER}@${EXEC_IP}"  
echo " Code-Agent:   ${CODE_IP}"  
echo " Volume:       ${BLK_PART} mounted at ${BUILD_ROOT} (label ${NVME_LABEL})"  
echo " Model:        ${BUILD_MODEL}"  
echo ""  
echo " Next, on the Code-Agent (${CODE_IP}), run install.sh. When section 9"  
echo " asks for the Build-Agent IP, enter:  ${EXEC_IP}"  
echo " Then paste the pubkey install.sh prints into:"  
echo "   ${USER_HOME}/.ssh/authorized_keys"  
echo "============================================================"
