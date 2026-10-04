#!/usr/bin/env bash  
# DizerCore-AI  
# ==================================================================  
# install-executor.sh — one-shot installer for the remote build  
# executor pi used by DizerCore-AI running on edith.  
#  
#   0. Asks for this machine's executor name (e.g. "buildpi") — used  
#      for the ext4 volume label, optional hostname, and all output.  
#   1. Detects the NVMe/SSD (excludes SD card / boot disk), lets the  
#      user pick, then ALWAYS wipes it (typed ERASE confirmation) ->  
#      new GPT + single ext4 partition labelled "<Name>Build".  
#   2. Mounts it by UUID at /mnt/build via fstab (nofail +  
#      x-systemd.device-timeout=10).  
#   3. Creates the "dizerbuild" service user + ~/.ssh/authorized_keys  
#      so the edith-generated key (~/.ssh/dizerbuild_ed25519.pub) can  
#      be pasted in.  
#   4. Installs build tooling + sandbox deps (bwrap, prlimit).  
#   5. Creates /mnt/build/jobs/ (rsync targets) and  
#      /mnt/build/repo.git (seeded bare repo for tree mode).  
#  
# Command contract (edith side, pipeline._remote_build):  
#   rsync -az -e "ssh -i KEY" <pkgdir>/  dizerbuild@HOST:/mnt/build/jobs/<id>/  
#   ssh  -i KEY dizerbuild@HOST prlimit --as=<MB>m --cpu=<S> \  
#        bwrap --unshare-all --bind /mnt/build/jobs/<id> /work \  
#        --chdir /work --dev /dev --proc /proc -- /bin/sh -lc "<cmd>"  
# ==================================================================  
set -Eeuo pipefail  
  
BUILD_USER="dizerbuild"  
BUILD_ROOT="/mnt/build"  
USER_HOME="/home/${BUILD_USER}"  
EXEC_NAME=""  
NVME_LABEL=""  
  
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
  
# ------------------------------------------------------------------  
# pick_build_disk — scan block devices, exclude the boot disk and SD  
# card, let the user choose. Sets BLK_DISK (whole disk, e.g.  
# /dev/nvme0n1). The picked disk is ALWAYS wiped.  
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
    [ "$(basename "$dev")" = "$root_disk" ] && continue        # boot disk  
    case "$dev" in  
      /dev/mmcblk*|/dev/loop*|/dev/zram*|/dev/ram*) continue ;; # SD card etc.  
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
    read -r -p "Which disk is the ${EXEC_NAME} build NVMe? [1-${#CANDS[@]}] " choice </dev/tty || true  
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#CANDS[@]}" ]; then  
      IFS='|' read -r BLK_DISK _sz _fs <<<"${CANDS[$((choice - 1))]}"  
      return 0  
    fi  
    warn "Enter a number between 1 and ${#CANDS[@]}."  
  done  
}  
  
# ------------------------------------------------------------------  
# wipe_build_disk — ERASE the picked disk: new GPT, one ext4 partition  
# labelled <ExecName>Build. Requires typing ERASE. Sets BLK_PART.  
# ------------------------------------------------------------------  
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
  
  # nvme/mmcblk/loop disks append pN, others append N.  
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
# 0. Banner + executor name + previous-install cleanup  
# ==================================================================  
banner "DizerCore build executor installer"  
require_tty  
  
echo ""  
echo "Name this build executor (used for the disk label and hostname)."  
echo "Examples: buildpi, executor1, pi2"  
while true; do  
  read -r -p "Executor name: " EXEC_NAME </dev/tty || true  
  EXEC_NAME="$(echo "$EXEC_NAME" | tr -d '[:space:]')"  
  if [[ "$EXEC_NAME" =~ ^[a-zA-Z][a-zA-Z0-9-]{0,30}$ ]]; then  
    break  
  fi  
  warn "Use 1-31 chars: letters, digits, hyphens; must start with a letter."  
done  
NVME_LABEL="${EXEC_NAME}Build"  
ok "Executor name: ${EXEC_NAME} (volume label: ${NVME_LABEL})"  
  
# Offer to set the system hostname to match.  
CUR_HOST="$(hostname 2>/dev/null || true)"  
if [ "$CUR_HOST" != "$EXEC_NAME" ]; then  
  if confirm "Set this machine's hostname to '${EXEC_NAME}' (currently '${CUR_HOST}')?"; then  
    echo "$EXEC_NAME" | sudo tee /etc/hostname >/dev/null  
    sudo hostnamectl set-hostname "$EXEC_NAME" 2>/dev/null || sudo hostname "$EXEC_NAME" || true  
    ok "Hostname set to ${EXEC_NAME}"  
  fi  
fi  
  
PREV=0  
id "$BUILD_USER" &>/dev/null && PREV=1  
[ -d "$BUILD_ROOT/jobs" ] && PREV=1  
  
if [ "$PREV" -eq 1 ]; then  
  echo ""  
  warn "A previous executor install was detected (user '${BUILD_USER}' or ${BUILD_ROOT} exists)."  
  echo "This will wipe the picked disk (ERASE), reset ${USER_HOME}/.ssh,"  
  echo "and re-create ${BUILD_ROOT}. Re-run is safe but destructive."  
  if ! confirm "Re-install the build executor?"; then  
    echo "Aborted."  
    exit 0  
  fi  
fi  
  
# ==================================================================  
# 1. System deps — build toolchain + sandbox (bwrap, prlimit, rsync)  
# ==================================================================  
ok "Installing system dependencies"  
sudo apt-get update -y  
sudo apt-get install -y git rsync build-essential cmake python3 \  
  bubblewrap util-linux parted  
  
# ==================================================================  
# 2. NVMe — pick, ERASE-wipe, format as <ExecName>Build  
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
# 4. dizerbuild service user + ~/.ssh  
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
  
# ==================================================================  
# 5. Build workspace layout on the NVMe  
# ==================================================================  
ok "Creating build layout under ${BUILD_ROOT}"  
sudo mkdir -p "${BUILD_ROOT}/jobs"          # rsync target, one dir per job  
sudo mkdir -p "${BUILD_ROOT}/repo.git"      # seeded bare repo (tree mode)  
if [ ! -f "${BUILD_ROOT}/repo.git/HEAD" ]; then  
  sudo git init --bare "${BUILD_ROOT}/repo.git"  
fi  
sudo chown -R "${BUILD_USER}:${BUILD_USER}" "$BUILD_ROOT"  
sudo chmod 755 "$BUILD_ROOT"  
  
# ==================================================================  
# 6. Done — hand back the authorized_keys path for install.sh section 9  
# ==================================================================  
echo ""  
banner "Build executor '${EXEC_NAME}' ready"  
echo " Host role:  ${EXEC_NAME} (${BUILD_USER}@${EXEC_NAME})"  
echo " Volume:     ${BLK_PART} mounted at ${BUILD_ROOT} (label ${NVME_LABEL})"  
echo ""  
echo " On edith, when install.sh section 9 shows the public key, append it to:"  
echo "   ${USER_HOME}/.ssh/authorized_keys"  
echo " (e.g.  sudo tee -a ${USER_HOME}/.ssh/authorized_keys <<< '<pubkey>')"  
echo ""  
echo " Edith will run:"  
echo "   rsync -> ${BUILD_ROOT}/jobs/<job_id>/"  
echo "   ssh ${BUILD_USER}@${EXEC_NAME} prlimit + bwrap <build_cmd>"  
echo "============================================================"
