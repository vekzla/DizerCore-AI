#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install-executor.sh — installer for the DizerCore-AI.Build-Agent pi  
# (the remote build executor). Normally reached via install.sh's role  
# picker, but also runnable directly.  
#  
#   1. Detects a previous install and offers: wipe clean / reuse.  
#   2. Asks for the Code-Agent's IP (the pi that will SSH in).  
#   3. Lists ALL non-boot disks, user picks by number, typed ERASE ->  
#      GPT + ext4 labelled "DizerCoreBuild". Re-run safe: unmounts  
#      existing mounts of the disk first.  
#   4. Mounts by UUID at /mnt/build (nofail + x-systemd.device-timeout).  
#   5. Creates "dizercorebuild" user + ~/.ssh/authorized_keys  
#      (preserved on "reuse" so the Code-Agent key survives).  
#   6. Installs a full build toolchain: C/C++ (gcc/g++, make, cmake,  
#      ninja, autoconf, pkg-config + common -dev libs), Python 3 + venv  
#      + pip, Node.js + npm, Go, Rust (cargo), Java (default-jdk) --  
#      plus sandbox deps: bubblewrap + util-linux (prlimit).  
#   7. Creates /mnt/build/jobs + /mnt/build/repo.git (bare).  
#   8. Asks the user for a repo URL AND optional branch to seed into  
#      repo.git (blank URL = skip; blank branch = repo default).  
#   9. Prints THIS machine's IP -- enter it into install.sh section 10  
#      on the Code-Agent, then paste the Code-Agent's pubkey into  
#      ~dizercorebuild/.ssh/authorized_keys.  
#  
# sshd on this pi must be reachable on port 22 from the Code-Agent.  
# ==================================================================  
set -euo pipefail  
  
ok()   { printf '\033[1;32m==>\033[0m %s\n' "$*"; }  
warn() { printf '\033[1;33m!!\033[0m %s\n'  "$*"; }  
die()  { printf '\033[1;31mXX\033[0m %s\n'  "$*"; exit 1; }  
  
banner() { echo "============================================================"; echo " $*"; echo "============================================================"; }  
  
BUILD_ROOT="/mnt/build"  
NVME_LABEL="DizerCoreBuild"  
BUILD_USER="dizercorebuild"  
  
banner "DizerCore-AI Build-Agent installer"  
echo ""  
  
ask_ip() {  
  local var="$1" prompt="$2" default="${3:-}" v=""  
  while :; do  
    if [ -n "$default" ]; then  
      read -r -p "${prompt} [${default}]: " v </dev/tty || true  
      v="${v:-$default}"  
    else  
      read -r -p "${prompt}: " v </dev/tty || true  
    fi  
    [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && { printf -v "$var" "%s" "$v"; return; }  
    echo "Enter a valid IPv4 address (e.g. 192.168.1.6)."  
  done  
}  
  
# ==================================================================  
# 0. Previous install?  Offer wipe-clean or reuse (like install.sh)  
# ==================================================================  
PREV_INSTALL="no"  
if id "$BUILD_USER" >/dev/null 2>&1 || findmnt -rn "$BUILD_ROOT" >/dev/null 2>&1; then  
  PREV_INSTALL="yes"  
fi  
  
FRESH_WIPE="yes"  
if [ "$PREV_INSTALL" = "yes" ]; then  
  banner "Previous Build-Agent install detected"  
  echo " Found: $(id "$BUILD_USER" >/dev/null 2>&1 && echo "user '${BUILD_USER}' ")$(findmnt -rn "$BUILD_ROOT" >/dev/null 2>&1 && echo "mounted ${BUILD_ROOT}")"  
  echo ""  
  echo "  [1] WIPE previous install  (fresh disk format, fresh keys)"  
  echo "  [2] REUSE                  (keep user + SSH key; reformat disk)"  
  local_pick=""  
  while :; do  
    read -r -p "Previous install [1-2]: " local_pick </dev/tty || true  
    case "$local_pick" in  
      1) FRESH_WIPE="yes"; break;;  
      2) FRESH_WIPE="no";  break;;  
      *) echo "Pick 1 or 2.";;  
    esac  
  done  
  if [ "$FRESH_WIPE" = "no" ]; then  
    warn "Reusing '${BUILD_USER}' user and ~/.ssh/authorized_keys."  
    warn "The Code-Agent will NOT need its pubkey re-pasted."  
  else  
    warn "Fresh wipe: '${BUILD_USER}' will be deleted and recreated;"  
    warn "you must re-paste the Code-Agent pubkey afterwards."  
  fi  
fi  
  
echo ""  
echo "This pi is the Build-Agent. The other pi runs the Code-Agent"  
echo "(the DizerCore pipeline that SSHes in to run builds)."  
ask_ip CODE_IP "Code-Agent IP address"  
ask_ip EXEC_IP "This Build-Agent's IP" "$(hostname -I | awk '{print $1}')"  
  
# ==================================================================  
# 1. Build toolchain + sandbox deps (single-line apt calls)  
# ==================================================================  
ok "Installing build toolchain"  
sudo apt-get update -y  
sudo apt-get install -y git rsync curl ca-certificates build-essential gcc g++ make cmake ninja-build || die "apt group A failed"  
sudo apt-get install -y autoconf automake libtool pkg-config || die "apt group B failed"  
sudo apt-get install -y python3 python3-venv python3-pip python3-dev || die "apt group C failed"  
sudo apt-get install -y nodejs npm || die "apt group D (nodejs/npm) failed"  
sudo apt-get install -y golang-go || die "apt group E (golang) failed"  
sudo apt-get install -y rustc cargo || die "apt group F (rust) failed"  
sudo apt-get install -y default-jdk-headless || warn "default-jdk-headless missing — Java builds unavailable"  
sudo apt-get install -y libssl-dev libffi-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev || die "apt group G (-dev libs) failed"  
sudo apt-get install -y bubblewrap util-linux parted openssh-server || die "apt group H (sandbox/ssh) failed"  
  
# ==================================================================  
# 2. Pick the build disk -- ALWAYS asks, numbered list, boot excluded  
# ==================================================================  
mapfile -t disks < <(lsblk -ndo NAME,TYPE | awk '$2=="disk"{print "/dev/"$1}')  
BOOT_SRC="$(findmnt -n -o SOURCE / 2>/dev/null || true)"  
BOOT_DISK=""  
case "$BOOT_SRC" in  
  /dev/mmcblk*) BOOT_DISK="/dev/$(echo "$BOOT_SRC" | sed 's|/dev/||; s|p[0-9]*$||')";;  
  /dev/sd*)     BOOT_DISK="$(echo "$BOOT_SRC" | sed 's|[0-9]*$||')";;  
  /dev/nvme*)   BOOT_DISK="$(echo "$BOOT_SRC" | sed 's|p[0-9]*$||')";;  
esac  
[ -n "$BOOT_DISK" ] && ok "Boot disk: ${BOOT_DISK} (excluded)"  
  
declare -a cand=()  
for d in "${disks[@]}"; do  
  [ -n "$BOOT_DISK" ] && [ "$d" = "$BOOT_DISK" ] && continue  
  case "$d" in /dev/mmcblk*|/dev/loop*|/dev/ram*|/dev/zram*) continue;; esac  
  sz="$(lsblk -ndo SIZE "$d" 2>/dev/null || echo '?')"  
  cand+=("$d"); ok "Detected non-boot disk: $d  $sz"  
done  
[ "${#cand[@]}" -gt 0 ] || die "No non-boot disk found."  
  
echo ""  
echo "Available build disks (boot disk excluded):"  
i=1  
for d in "${cand[@]}"; do  
  sz="$(lsblk -ndo SIZE "$d" 2>/dev/null || echo '?')"  
  echo "  [$i] $d  $sz"  
  i=$((i+1))  
done  
BLK_DISK=""  
while :; do  
  n=""  
  read -r -p "Build disk number [1-${#cand[@]}]: " n </dev/tty || true  
  [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "${#cand[@]}" ] && { BLK_DISK="${cand[$((n-1))]}"; break; }  
  echo "Pick a number 1-${#cand[@]}."  
done  
ok "Using $BLK_DISK for the build volume"  
  
# ==================================================================  
# 3. Ask for repo URL + branch BEFORE the wipe (all questions first)  
# ==================================================================  
echo ""  
read -r -p "Repo URL to seed into ${BUILD_ROOT}/repo.git (blank = skip): " SEED_REPO </dev/tty || true  
SEED_BRANCH=""  
if [ -n "$SEED_REPO" ]; then  
  read -r -p "Branch to seed (blank = repo default branch): " SEED_BRANCH </dev/tty || true  
fi  
  
# ==================================================================  
# 4. Wipe confirm + format  
# ==================================================================  
echo ""  
warn "ALL DATA on ${BLK_DISK} WILL BE ERASED"  
lsblk "$BLK_DISK" || true  
ANS=""  
read -r -p "Type ERASE to wipe ${BLK_DISK}: " ANS </dev/tty || true  
[ "$ANS" = "ERASE" ] || die "Aborted — disk untouched."  
  
mnt=""  
while read -r mnt; do  
  [ -n "$mnt" ] || continue  
  warn "Unmounting ${mnt} (re-install)"  
  sudo umount "$mnt" || die "Could not unmount ${mnt} — close anything using it and re-run."  
done < <(lsblk -n -o MOUNTPOINT "$BLK_DISK" 2>/dev/null | grep -v '^$' || true)  
sudo sed -i "\| ${BUILD_ROOT} |d" /etc/fstab  
sudo systemctl daemon-reload 2>/dev/null || true  
  
sudo wipefs -a "$BLK_DISK"  
sudo parted -s "$BLK_DISK" mklabel gpt  
sudo parted -s "$BLK_DISK" mkpart primary ext4 1MiB 100%  
sudo partprobe "$BLK_DISK" 2>/dev/null || true  
sleep 2  
case "$BLK_DISK" in  
  *nvme*|*mmcblk*) BLK_PART="${BLK_DISK}p1";;  
  *)               BLK_PART="${BLK_DISK}1";;  
esac  
[ -b "$BLK_PART" ] || die "Partition ${BLK_PART} not found after parted."  
sudo mkfs.ext4 -F -L "$NVME_LABEL" "$BLK_PART"  
ok "Wipe complete; using $BLK_PART"  
  
# ==================================================================  
# 5. Mount at /mnt/build by UUID  
# ==================================================================  
ok "Mounting the build volume at ${BUILD_ROOT}"  
sudo mkdir -p "$BUILD_ROOT"  
BLK_UUID="$(sudo blkid -s UUID -o value "$BLK_PART" || true)"  
[ -n "$BLK_UUID" ] || die "blkid returned no UUID for $BLK_PART"  
grep -q "$BLK_UUID" /etc/fstab || echo "UUID=${BLK_UUID}  ${BUILD_ROOT}  ext4  defaults,nofail,x-systemd.device-timeout=5s  0  2" | sudo tee -a /etc/fstab >/dev/null  
sudo mount "$BLK_PART" "$BUILD_ROOT"  
grep -q "$BLK_UUID" /proc/mounts || die "${BUILD_ROOT} did not mount."  
  
# ==================================================================  
# 6. dizercorebuild user + ssh dir (deleted on fresh wipe; reused else)  
# ==================================================================  
if [ "$FRESH_WIPE" = "yes" ] && id "$BUILD_USER" >/dev/null 2>&1; then  
  ok "Removing previous '${BUILD_USER}' user (fresh wipe)"  
  sudo userdel -r "$BUILD_USER" 2>/dev/null || true  
fi  
if ! id "$BUILD_USER" >/dev/null 2>&1; then  
  ok "Creating '${BUILD_USER}' service user"  
  sudo useradd -m -s /bin/bash "$BUILD_USER"  
else  
  ok "Reusing existing '${BUILD_USER}' user"  
fi  
USER_HOME="$(getent passwd "$BUILD_USER" | cut -d: -f6)"  
sudo mkdir -p "${USER_HOME}/.ssh"  
sudo touch "${USER_HOME}/.ssh/authorized_keys"  
sudo chmod 700 "${USER_HOME}/.ssh"  
sudo chmod 600 "${USER_HOME}/.ssh/authorized_keys"  
sudo chown -R "${BUILD_USER}:${BUILD_USER}" "${USER_HOME}/.ssh"  
sudo systemctl enable --now ssh 2>/dev/null || true  
  
# ==================================================================  
# 7. Build workspace layout  
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
# 8. Seed repo.git from the user-supplied URL (+ optional branch)  
# ==================================================================  
if [ -n "$SEED_REPO" ]; then  
  if [ -n "$SEED_BRANCH" ]; then  
    ok "Cloning ${SEED_REPO} (branch: ${SEED_BRANCH}) into ${BUILD_ROOT}/repo.git"  
    sudo rm -rf "${BUILD_ROOT}/repo.git"  
    sudo -u "$BUILD_USER" git clone --bare --branch "$SEED_BRANCH" --single-branch "$SEED_REPO" "${BUILD_ROOT}/repo.git" || die "Clone failed — check the URL, the branch name, and network."  
  else  
    ok "Cloning ${SEED_REPO} (default branch) into ${BUILD_ROOT}/repo.git"  
    sudo rm -rf "${BUILD_ROOT}/repo.git"  
    sudo -u "$BUILD_USER" git clone --bare "$SEED_REPO" "${BUILD_ROOT}/repo.git" || die "Clone failed — check the URL and network."  
  fi  
  sudo chown -R "${BUILD_USER}:${BUILD_USER}" "${BUILD_ROOT}/repo.git"  
  ok "repo.git seeded — tree-mode builds clone it locally"  
  warn "Add ${SEED_REPO} verbatim to ALLOWED_REPOS on the Code-Agent or /run 400s it."  
else  
  warn "Skipped — ${BUILD_ROOT}/repo.git stays an empty bare repo."  
  warn "Tree-mode builds will clone the allowlisted URL directly."  
fi  
  
# ==================================================================  
# 9. Done  
# ==================================================================  
echo ""  
banner "DizerCore-AI Build-Agent ready"  
echo " This pi:      ${BUILD_USER}@${EXEC_IP}"  
echo " Code-Agent:   ${CODE_IP}"  
echo " Volume:       ${BLK_PART} mounted at ${BUILD_ROOT} (label ${NVME_LABEL})"  
[ -n "$SEED_REPO" ] && echo " Seeded repo:  ${SEED_REPO}${SEED_BRANCH:+ (branch ${SEED_BRANCH})}"  
echo " Toolchain:    gcc/g++, make, cmake, ninja, python3+venv, node+npm,"  
echo "               go, cargo/rustc, java, bwrap+prlimit"  
echo ""  
echo " Next, on the Code-Agent (${CODE_IP}), run install.sh. When section 10"  
echo " asks for the Build-Agent IP, enter:  ${EXEC_IP}"  
if [ "$FRESH_WIPE" = "yes" ]; then  
  echo " Then paste the pubkey install.sh prints into:"  
  echo "   ${USER_HOME}/.ssh/authorized_keys"  
else  
  echo " SSH key was preserved (reuse) — no re-paste needed."  
fi  
echo "============================================================"
