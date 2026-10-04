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
#      typed ERASE -> GPT + ext4 labelled "DizerCoreBuild".  
#      Re-run safe: unmounts existing mounts of the disk first.  
#   3. Mounts by UUID at /mnt/build (nofail + x-systemd.device-timeout).  
#   4. Creates "dizercorebuild" user + ~/.ssh/authorized_keys.  
#   5. Installs a full build toolchain: C/C++ (gcc/g++, make, cmake,  
#      ninja, autoconf, pkg-config + common -dev libs), Python 3 + venv  
#      + pip, Node.js + npm, Go, Rust (cargo), Java (default-jdk) —  
#      plus sandbox deps (bwrap, prlimit).  
#   6. Creates /mnt/build/jobs/ + /mnt/build/repo.git, and optionally  
#      pulls the DizerCore-AI repo into the bare repo (tree mode).  
#   7. Prints THIS machine's IP — enter it into install.sh section 9  
#      on the Code-Agent.  
#  
# Command contract (Code-Agent side, pipeline._remote_build):  
#   rsync -az -e "ssh -i KEY" <pkgdir>/  dizercorebuild@IP:/mnt/build/jobs/<id>/  
#   ssh  -i KEY dizercorebuild@IP sh -c  
#        'prlimit --as=<MB>m --cpu=<S>  
#         bwrap --unshare-all --bind /mnt/build/jobs/<id> /work  
#         --chdir /work --dev /dev --proc /proc -- /bin/sh -lc "<cmd>"'  
#   (the ssh args are one command — written wrapped here for docs only;  
#    pipeline.py passes them as a single argv array, no shell join)  
# ==================================================================  
set -Eeuo pipefail  
  
BUILD_USER="dizercorebuild"  
BUILD_ROOT="/mnt/build"  
NVME_LABEL="DizerCoreBuild"  
USER_HOME="/home/${BUILD_USER}"  
  
# Repo pulled into the bare repo for tree-mode builds — override with  
# REPO_URL env if the app repo moves.  
REPO_URL="${REPO_URL:-https://github.com/vekzla/DizerCore-AI.git}"  
  
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
  root_disk="$(basename "$(lsblk -n -o PKNAME "$root_src" 2>/dev/null || echo "")")"  
  [ -n "$root_disk" ] || root_disk="$(lsblk -n -o NAME | head -n1)"  
  
  local disks=() dev sz  
  while read -r dev sz; do  
    [[ "$dev" == /dev/mmcblk* ]] && continue           # SD card  
    [[ "$dev" == /dev/loop*   || "$dev" == /dev/zram* ]] && continue  
    [[ "$(basename "$dev")" == "$root_disk" ]] && continue  # boot disk  
    disks+=("${dev}  ${sz}")  
  done < <(lsblk -b -d -n -o PATH,SIZE 2>/dev/null | while read -r path size; do echo "$path $(numfmt --to=iec --suffix=B "$size" 2>/dev/null || echo "$size")"; done)  
  [ "${#disks[@]}" -gt 0 ] || die "No non-boot disk found — is the NVMe/SSD attached?"  
  
  if [ "${#disks[@]}" -eq 1 ]; then  
    ok "Detected build disk: ${disks[0]}"  
    BLK_DISK="${disks[0]%%  *}"  
  else  
    echo "Multiple non-boot disks found:"  
    local i=1  
    for d in "${disks[@]}"; do echo "  [$i] $d"; i=$((i+1)); done  
    local n=""  
    while true; do  
      read -r -p "Build disk number [1-${#disks[@]}]: " n </dev/tty || true  
      [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "${#disks[@]}" ] && break  
    done  
    BLK_DISK="${disks[$((n-1))]%%  *}"  
  fi  
}  
  
wipe_build_disk() {  
  warn "ALL DATA on ${BLK_DISK} WILL BE ERASED"  
  lsblk "$BLK_DISK" || true  
  local ans=""  
  read -r -p "Type ERASE to wipe ${BLK_DISK}: " ans </dev/tty || true  
  [ "$ans" = "ERASE" ] || die "Wipe aborted."  
  
  # Re-run safe: unmount every mount sourced from this disk, then drop  
  # stale fstab entries for BUILD_ROOT so mount -a can't resurrect the  
  # old filesystem while we wipe.  
  local mnt=""  
  while read -r mnt; do  
    [ -n "$mnt" ] || continue  
    warn "Unmounting ${mnt} (re-install)"  
    sudo umount "$mnt" || die "Could not unmount ${mnt} — close anything using it and re-run."  
  done < <(lsblk -n -o MOUNTPOINT "$BLK_DISK" 2>/dev/null | grep -v '^$' || true)  
  sudo sed -i "\| ${BUILD_ROOT} |d" /etc/fstab  
  sudo systemctl daemon-reload 2>/dev/null || true  
  
  sudo wipefs -a "$BLK_DISK"  
  sudo parted -s "$BLK_DISK" mklabel gpt  
  sudo parted -s "$BLK_DISK" mkpart primary ext4 0% 100%  
  sudo partprobe "$BLK_DISK" || true  
  sleep 1  
  
  # Partition node: nvme/mmcblk/loop append 'p1'; sda/sdb append '1'.  
  if [[ "$(basename "$BLK_DISK")" =~ ^(nvme|mmcblk|loop) ]]; then  
    BLK_PART="${BLK_DISK}p1"  
  else  
    BLK_PART="${BLK_DISK}1"  
  fi  
  [ -b "$BLK_PART" ] || die "Expected partition ${BLK_PART} not found."  
  
  sudo mkfs.ext4 -F -L "$NVME_LABEL" "$BLK_PART"  
}  
  
# ==================================================================  
# 0. Preamble — both pis' IPs  
# ==================================================================  
banner "DizerCore-AI Build-Agent installer"  
require_tty  
  
echo ""  
echo "This pi is the Build-Agent. The other pi runs the Code-Agent"  
echo "(the DizerCore pipeline that SSHes in to run builds)."  
ask_ip "Code-Agent IP address"  
CODE_IP="$REPLY_IP"  
ask_ip "This Build-Agent's IP" "$(hostname -I | awk '{print $1}')"  
EXEC_IP="$REPLY_IP"  
  
# ==================================================================  
# 1. System dependencies + full build toolchain  
#    NOTE: one install per line — no backslash continuations. A stray  
#    space after a \ turns it into an escaped space and apt gets an  
#    empty package name ("Unable to locate package").  
# ==================================================================  
ok "Installing system dependencies"  
sudo apt-get update -y  
sudo apt-get install -y git rsync curl ca-certificates || die "apt failed: base tools"  
sudo apt-get install -y build-essential gcc g++ make cmake ninja-build || die "apt failed: C/C++ toolchain"  
sudo apt-get install -y autoconf automake libtool pkg-config || die "apt failed: autotools"  
sudo apt-get install -y python3 python3-venv python3-pip python3-dev || die "apt failed: python"  
sudo apt-get install -y nodejs npm golang-go rustc cargo || die "apt failed: node/go/rust"  
sudo apt-get install -y default-jdk-headless || warn "default-jdk-headless missing — Java builds unavailable"  
sudo apt-get install -y libssl-dev libffi-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev || die "apt failed: -dev libs"  
sudo apt-get install -y bubblewrap util-linux parted openssh-server || die "apt failed: sandbox deps"  
  
# ==================================================================  
# 2. NVMe — pick, ERASE-wipe, format as DizerCoreBuild  
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
# 4. dizercorebuild service user + ~/.ssh (keyed from the Code-Agent)  
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
# 6. Pull the app repo into the bare repo (tree-mode seed)  
# ==================================================================  
if confirm "Pull ${REPO_URL} into ${BUILD_ROOT}/repo.git now?"; then  
  ok "Cloning ${REPO_URL} into ${BUILD_ROOT}/repo.git"  
  sudo rm -rf "${BUILD_ROOT}/repo.git"  
  sudo -u "$BUILD_USER" git clone --bare "$REPO_URL" "${BUILD_ROOT}/repo.git" || die "Clone failed — check the URL and network, or skip and pull later."  
  ok "repo.git seeded at ${BUILD_ROOT}/repo.git"  
else  
  warn "Skipped — ${BUILD_ROOT}/repo.git stays an empty bare repo."  
  warn "Tree-mode builds will clone the allowlisted URL directly."  
fi  
  
# ==================================================================  
# 7. Done  
# ==================================================================  
echo ""  
banner "DizerCore-AI Build-Agent ready"  
echo " This pi:      ${BUILD_USER}@${EXEC_IP}"  
echo " Code-Agent:   ${CODE_IP}"  
echo " Volume:       ${BLK_PART} mounted at ${BUILD_ROOT} (label ${NVME_LABEL})"  
echo " Toolchain:    gcc/g++, make, cmake, ninja, python3+venv, node+npm,"  
echo "               go, cargo/rustc, java, bwrap+prlimit"  
echo ""  
echo " Next, on the Code-Agent (${CODE_IP}), run install.sh. When section 9"  
echo " asks for the Build-Agent IP, enter:  ${EXEC_IP}"  
echo " Then paste the pubkey install.sh prints into:"  
echo "   ${USER_HOME}/.ssh/authorized_keys"  
echo "============================================================"
