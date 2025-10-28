#!/usr/bin/env bash
# Recover USB SSD par paliers — DIAG enrichi + métriques + JSON pour Home Assistant.
# Étapes: 0 Diagnostic | 1 Remount/Mount | 2 SCSI Rescan | 3 Unmount(+escalade) + Delete/Scan | 4 USB Reset | 5 uhubctl (option)
# Exit codes: 0=OK, 3=Impossible d’unmount, 4=Échec final, 6=OK mais unmount forcé utilisé

set -euo pipefail

# ====== CIBLES À ADAPTER SI BESOIN ======
MNT="/mnt/usbdata"
BYUUID="/dev/disk/by-uuid/7f3a823c-fa79-4162-be0e-197a3ad5918c"

# ===== Résolution dynamique du device =====
resolve_block_vars() {
  local src pk
  src="$(findmnt -no SOURCE "$MNT" 2>/dev/null || true)"
  if [[ -z "$src" && -e "$BYUUID" ]]; then
    src="$(readlink -f "$BYUUID" 2>/dev/null || true)"
  fi
  if [[ -z "$src" ]]; then
    src="$(lsblk -o NAME,MOUNTPOINT -nr 2>/dev/null | awk -v m="$MNT" '$2==m{print "/dev/"$1; exit}')"
  fi
  PART=""; DEV=""; DEVBASE=""
  if [[ -n "$src" ]]; then
    PART="$src"
    pk="$(lsblk -no PKNAME "$PART" 2>/dev/null | head -n1)"
    if [[ -n "$pk" ]]; then
      DEV="/dev/$pk"
    else
      DEV="${PART%[0-9]*}"
      [[ "$DEV" == "$PART" ]] && DEV="$PART"
    fi
    DEVBASE="$(basename "$DEV")"
  fi
}

# 1er calcul au démarrage
resolve_block_vars

# ====== COMPORTEMENT ======
DO_USB_RESET=1   # 1 = tenter unbind/bind USB à l’étape 4
DO_UHUBCTL=0     # 1 = tenter uhubctl à l’étape 5
UHUB_LOC="1-2"
UHUB_PORT="3"

# ===== Helpers format/affichage =====
ts(){ date +"%F %T"; }
say(){ echo "[$(ts)] $*"; }

# ===== Test de santé (probe léger) =====
probe_health_json() {
  local mnt="$1"
  local ls_ok=0 write_ok=0 read_ok=0 reason=""
  local f

  if mountpoint -q "$mnt"; then
    if ls -ld "$mnt" >/dev/null 2>&1; then ls_ok=1; else reason="ls_fail"; fi
    f="$mnt/.io_probe_diag.$$"
    if dd if=/dev/zero of="$f" bs=4K count=1 oflag=dsync status=none >/dev/null 2>&1; then
      write_ok=1
      if head -c 1 "$f" >/dev/null 2>&1; then
        read_ok=1
      else
        reason="${reason:-read_fail}"
      fi
    else
      reason="${reason:-write_fail}"
    fi
    rm -f "$f" >/dev/null 2>&1 || true
  else
    reason="not_mounted"
  fi

  local health
  if [[ $ls_ok -eq 1 && $write_ok -eq 1 && $read_ok -eq 1 ]]; then health="OK"; else health="NOK"; fi
  echo "{\"ls_ok\":$ls_ok,\"write_ok\":$write_ok,\"read_ok\":$read_ok,\"health\":\"$health\",\"reason\":\"$reason\"}"
}

# ===== Helpers sysfs/USB =====
usb_node() {
  local devbase="$1"
  [[ -z "${devbase:-}" ]] && { echo ""; return; }
  local p; p="$(readlink -f "/sys/block/$devbase" 2>/dev/null || true)"
  echo "$p" | sed -n 's#.*\(usb[0-9]\+/[0-9-]\+\).*#\1#p' | awk -F/ '{print $2}' || true
}
usb_bus_dev_from_sysfs() {
  local node="$1"
  [[ -z "$node" ]] && { echo "?/?"; return; }
  local bus dev
  bus="$(cat "/sys/bus/usb/devices/$node/busnum" 2>/dev/null || echo "?")"
  dev="$(cat "/sys/bus/usb/devices/$node/devnum" 2>/dev/null || echo "?")"
  echo "$bus/$dev"
}
usb_driver_speed() {
  # Renvoie: "driver|mbps"
  local node="$1"
  local iface drv spd_raw mbps
  if [[ -n "$node" ]]; then
    iface="$(ls -d "/sys/bus/usb/devices/${node}:"* 2>/dev/null | head -n1 || true)"
    if [[ -n "$iface" && -e "$iface/driver" ]]; then
      drv="$(basename "$(readlink -f "$iface/driver")" 2>/dev/null)"
    else
      drv="$(lsusb -t 2>/dev/null | awk "/${node//-/.}/ && /Driver=/{for(i=1;i<=NF;i++) if(\$i ~ /^Driver=/){gsub(\"Driver=\",\"\",\$i); print \$i; exit}}")"
    fi
    spd_raw="$(cat "/sys/bus/usb/devices/$node/speed" 2>/dev/null || echo "")"
  fi
  [[ -n "${spd_raw:-}" ]] && mbps="$(printf "%.0f" "$spd_raw")" || mbps=""
  echo "${drv:-}|${mbps}"
}
usb_power_autosuspend() {
  # Renvoie: "control|delay_ms|runtime_status|suspended_time_s"
  local node="$1"
  local ctl status stime delay
  if [[ -z "$node" ]]; then echo "?|0|?|0"; return; fi
  ctl="$(cat "/sys/bus/usb/devices/$node/power/control" 2>/dev/null || echo "?")"
  status="$(cat "/sys/bus/usb/devices/$node/power/runtime_status" 2>/dev/null || echo "?")"
  if [[ -r "/sys/bus/usb/devices/$node/power/runtime_suspended_time" ]]; then
    local us; us="$(cat "/sys/bus/usb/devices/$node/power/runtime_suspended_time" 2>/dev/null || echo 0)"
    stime=$(( us/1000000 ))
  else
    stime=0
  fi
  if [[ -r "/sys/bus/usb/devices/$node/power/autosuspend_delay_ms" ]]; then
    delay="$(cat "/sys/bus/usb/devices/$node/power/autosuspend_delay_ms" 2>/dev/null || echo 0)"
  elif [[ -r "/sys/bus/usb/devices/$node/power/autosuspend" ]]; then
    local sec; sec="$(cat "/sys/bus/usb/devices/$node/power/autosuspend" 2>/dev/null || echo 0)"
    delay=$(( sec * 1000 ))
  else
    delay=0
  fi
  if [[ "$delay" -gt 600000 && -r "/sys/bus/usb/devices/$node/power/autosuspend_delay_ms" ]]; then
    delay=$(( delay / 1000 ))
  fi
  echo "$ctl|${delay}|${status}|${stime}"
}

# ===== Helpers métriques FS =====
fs_metrics_json() {
  local mnt="$1"
  local used avail total pcent in_used in_free dirs1 files_total
  if mountpoint -q "$mnt"; then
    read used avail total < <(df -B1 --output=used,avail,size "$mnt" 2>/dev/null | awk 'NR==2{print $1, $2, $3}')
    pcent="$(df --output=pcent "$mnt" 2>/dev/null | awk 'NR==2{gsub(/%/,"");print $1}')"
    in_used="$(df -i --output=iused "$mnt" 2>/dev/null | awk 'NR==2{print $1}')"
    in_free="$(df -i --output=ifree "$mnt" 2>/dev/null | awk 'NR==2{print $1}')"
    dirs1="$(timeout 5s find "$mnt" -mindepth 1 -maxdepth 1 -type d -printf '.' 2>/dev/null | wc -c)"
    files_total="$(timeout 10s find "$mnt" -xdev -type f -printf '.' 2>/dev/null | wc -c)"
  else
    used=0; avail=0; total=0; pcent=0; in_used=0; in_free=0; dirs1=0; files_total=0
  fi
  cat <<JSON
{"bytes_total":${total:-0},"bytes_used":${used:-0},"bytes_avail":${avail:-0},"pct_used":${pcent:-0},"inodes_used":${in_used:-0},"inodes_free":${in_free:-0},"dirs_top":${dirs1:-0},"files_total":${files_total:-0}}
JSON
}

# ===== Mode Home Assistant: DIAG JSON (aucune réparation) =====
if [[ "${1:-}" == "--diag" ]]; then
  resolve_block_vars
  USB_NODE="$(usb_node "${DEVBASE:-}")"
  BUSDEV="$(usb_bus_dev_from_sysfs "$USB_NODE")"
  DRVSPD="$(usb_driver_speed "$USB_NODE")"
  USB_DRV="${DRVSPD%%|*}"; USB_Mbps="${DRVSPD##*|}"
  if [[ -n "$USB_Mbps" ]]; then USB_Gbps="$(awk -v m="$USB_Mbps" 'BEGIN{printf("%.1f", m/1000)}')"; else USB_Gbps=""; fi

  # État de montage
  if mountpoint -q "$MNT"; then
    if mount | grep -E " on ${MNT//\//\\/} " | grep -q "(ro,"; then MOUNT_MODE="ro"; else MOUNT_MODE="rw"; fi
  else
    MOUNT_MODE="down"
  fi

  HEALTH="$(probe_health_json "$MNT")"
  AUTOS="$(usb_power_autosuspend "$USB_NODE")"
  AUTO_CTL="${AUTOS%%|*}"; local tmp; tmp="${AUTOS#*|}"; AUTO_DELAY="${tmp%%|*}"; tmp="${tmp#*|}"; AUTO_STATUS="${tmp%%|*}"; AUTO_STIME="${tmp##*|}"
  MET="$(fs_metrics_json "$MNT")"

  printf '{'
  printf '"uuid":"%s",'  "${BYUUID#/dev/disk/by-uuid/}"
  printf '"mount_mode":"%s",' "$MOUNT_MODE"
  printf '"partition":"%s","disk":"%s",' "${PART:-}","${DEV:-}"
  printf '"usb_node":"%s","usb_busdev":"%s",' "${USB_NODE:-}" "${BUSDEV:-}"
  printf '"usb_driver":"%s","usb_speed_mbps":%s,"usb_speed_gbps":%s,' "${USB_DRV:-}" "${USB_Mbps:-0}" "${USB_Gbps:-0}"
  printf '"usb_power_control":"%s","usb_autosuspend_ms":%s,' "${AUTO_CTL:-}" "${AUTO_DELAY:-0}"
  printf '"usb_runtime_status":"%s","usb_suspended_time_s":%s,' "${AUTO_STATUS:-}" "${AUTO_STIME:-0}"
  echo "$MET" | sed 's/^{//; s/}$//' | tr -d '\n'
  printf ','
  echo "$HEALTH" | sed 's/^{//; s/}$//' | tr -d '\n'
  printf '}\n'
  exit 0
fi

# ================= Palier 0 : Diagnostic enrichi =================
resolve_block_vars
say "== Palier 0: Diagnostic =="

USB_NODE="$(usb_node "${DEVBASE:-}")"
BUSDEV="$(usb_bus_dev_from_sysfs "$USB_NODE")"
DRVSPD="$(usb_driver_speed "$USB_NODE")"
USB_DRV="${DRVSPD%%|*}"; USB_Mbps="${DRVSPD##*|}"
if [[ -n "$USB_Mbps" ]]; then USB_Gbps="$(awk -v m="$USB_Mbps" 'BEGIN{printf("%.1f", m/1000)}')"; else USB_Gbps=""; fi
AUTOS="$(usb_power_autosuspend "$USB_NODE")"
AUTO_CTL="${AUTOS%%|*}"; tmp="${AUTOS#*|}"; AUTO_DELAY="${tmp%%|*}"; tmp="${tmp#*|}"; AUTO_STATUS="${tmp%%|*}"; AUTO_STIME="${tmp##*|}"

say "==== 0) Résolution device / nœud USB ===="
say " UUID                        : ${BYUUID#/dev/disk/by-uuid/}"
say " Partition                   : ${PART:-?}"
say " Disque                      : ${DEV:-?}"
say " USB node                    : ${USB_NODE:-?}"
say " USB Bus/Dev                 : ${BUSDEV:-?}"

say ""
say "==== 1) Driver + Vitesse (ligne exacte Bus/Dev) ===="
CTX="$(lsusb -t 2>/dev/null | sed -n '1,4p')"
[[ -n "$CTX" ]] && echo "$CTX"
say " -> Driver                   : ${USB_DRV:-?}"
if [[ -n "${USB_Mbps:-}" && "$USB_Mbps" -gt 0 ]]; then
  say " -> Speed                    : ${USB_Gbps} Gbit/s (${USB_Mbps} Mb/s)"
else
  say " -> Speed                    : inconnu"
fi

say ""
say "==== 3) Autosuspend (device & interface) ===="
say " [${USB_NODE:-?}] control               : ${AUTO_CTL:-?}"
say " [${USB_NODE:-?}] autosuspend(ms)       : ${AUTO_DELAY:-?}"
say " [${USB_NODE:-?}] runtime_status        : ${AUTO_STATUS:-?}"
say " [${USB_NODE:-?}] suspended_time        : ${AUTO_STIME:-0}"

MET="$(fs_metrics_json "$MNT")"
BT=$(echo "$MET" | grep -o '"bytes_total":[0-9]*' | cut -d: -f2)
BU=$(echo "$MET" | grep -o '"bytes_used":[0-9]*'  | cut -d: -f2)
PU=$(echo "$MET" | grep -o '"pct_used":[0-9]*'    | cut -d: -f2)
DT=$(echo "$MET" | grep -o '"dirs_top":[0-9]*'    | cut -d: -f2)
FT=$(echo "$MET" | grep -o '"files_total":[0-9]*' | cut -d: -f2)

say ""
say "==== Disque (métriques) ===="
say " Taille disque (B)           : ${BT:-0}"
say " Taille occupée (B)          : ${BU:-0}"
say " % d'occupation              : ${PU:-0}"
say " Dossiers (1er niveau)       : ${DT:-0}"
say " Fichiers (total)            : ${FT:-0}"

if mountpoint -q "$MNT"; then
  mount | grep -E " on ${MNT//\//\\/} " | grep -q "(ro," && say "RESULT: MONTAGE = RO" || say "RESULT: MONTAGE = RW"
  if head -c 1 "$MNT" >/dev/null 2>&1; then say "RESULT: Lecture racine = OK"; else say "RESULT: Lecture racine = FAIL (EIO probable)"; fi
else
  say "RESULT: MONTAGE = non monté"
fi

# Si déjà RW opérationnel, on sort avec 0 (pas d'erreur pour HA)
if mountpoint -q "$MNT" && mount | grep -E " on ${MNT//\//\\/} " | grep -q "(rw,"; then
  TMP="$MNT/.io_probe_status.$$"
  if dd if=/dev/zero of="$TMP" bs=4K count=1 oflag=dsync status=none >/dev/null 2>&1; then
    rm -f "$TMP" 2>/dev/null || true
    say "RESULT: Déjà OK (écriture possible) — sortie."
    exit 0
  fi
fi

# ================= Palier 1 : Remount/Mount non intrusif =================
RES="NOPE"
if mountpoint -q "$MNT"; then
  mount -o remount,rw,noatime "$MNT" >/dev/null 2>&1 || true
else
  mount "$BYUUID" "$MNT" >/dev/null 2>&1 || mount "${PART:-}" "$MNT" >/dev/null 2>&1 || true
fi
if mountpoint -q "$MNT"; then
  TMP="$MNT/.io_probe_p1.$$"
  if dd if=/dev/zero of="$TMP" bs=4K count=1 oflag=dsync status=none >/dev/null 2>&1; then rm -f "$TMP" 2>/dev/null || true; RES="SUCCESS"; fi
fi
say "RESULT: Palier 1 = $RES"
[[ "$RES" == "SUCCESS" ]] && exit 0

# ================= Palier 2 : SCSI Rescan non intrusif =================
resolve_block_vars
RES="NOPE"
if [[ -n "${DEVBASE:-}" && -e "/sys/block/$DEVBASE/device/rescan" ]]; then
  echo 1 > "/sys/block/$DEVBASE/device/rescan"
  udevadm settle >/dev/null 2>&1 || true
  sleep 1
fi
if ! mountpoint -q "$MNT"; then
  mount "$BYUUID" "$MNT" >/dev/null 2>&1 || mount "${PART:-}" "$MNT" >/dev/null 2>&1 || true
fi
if mountpoint -q "$MNT"; then
  TMP="$MNT/.io_probe_p2.$$"
  if dd if=/dev/zero of="$TMP" bs=4K count=1 oflag=dsync status=none >/dev/null 2>&1; then rm -f "$TMP" 2>/dev/null || true; RES="SUCCESS"; fi
fi
say "RESULT: Palier 2 = $RES"
[[ "$RES" == "SUCCESS" ]] && exit 0

# ================= Palier 3 : Unmount (normal → lazy → force) + Delete/Scan + Remount =================
FORCED=0
RES_UNMOUNT="OK"
if mountpoint -q "$MNT"; then
  if ! umount "$MNT" >/dev/null 2>&1; then
    if ! umount -l "$MNT" >/dev/null 2>&1; then
      if ! umount -f "$MNT" >/dev/null 2>&1; then
        RES_UNMOUNT="FAIL"
      else
        FORCED=1
      fi
    fi
  fi
fi
if [[ "$RES_UNMOUNT" == "FAIL" ]]; then
  say "RESULT: Palier 3 = FAIL (unmount impossible)"
  exit 3
fi

# delete + rescan (le nom peut changer)
if [[ -n "${DEVBASE:-}" && -e "/sys/block/$DEVBASE/device/delete" ]]; then
  echo 1 > "/sys/block/$DEVBASE/device/delete"
fi
for h in /sys/class/scsi_host/host*; do echo "- - -" > "$h/scan"; done
udevadm settle >/dev/null 2>&1 || true
sleep 2

resolve_block_vars
RES="NOPE"
if mount "$BYUUID" "$MNT" >/dev/null 2>&1 || mount "${PART:-}" "$MNT" >/dev/null 2>&1; then RES="SUCCESS"; fi
say "RESULT: Palier 3 = $RES"
if [[ "$RES" == "SUCCESS" ]]; then [[ $FORCED -eq 1 ]] && exit 6 || exit 0; fi

# ================= Palier 4 : USB unbind/bind =================
resolve_block_vars
USB_NODE="$(usb_node "${DEVBASE:-}")"
RES="SKIP"
if [[ ${DO_USB_RESET} -eq 1 && -n "${USB_NODE:-}" ]]; then
  echo -n "$USB_NODE" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
  sleep 1
  echo -n "$USB_NODE" > /sys/bus/usb/drivers/usb/bind  2>/dev/null || true
  udevadm settle >/dev/null 2>&1 || true
  sleep 2
  resolve_block_vars
  if mount "$BYUUID" "$MNT" >/dev/null 2>&1 || mount "${PART:-}" "$MNT" >/dev/null 2>&1; then RES="SUCCESS"; else RES="NOPE"; fi
fi
say "RESULT: Palier 4 = $RES"
if [[ "$RES" == "SUCCESS" ]]; then [[ $FORCED -eq 1 ]] && exit 6 || exit 0; fi

# ================= Palier 5 : uhubctl (optionnel) =================
RES="SKIP"
if [[ ${DO_UHUBCTL} -eq 1 ]] && command -v uhubctl >/dev/null 2>&1; then
  uhubctl -l "$UHUB_LOC" -p "$UHUB_PORT" -a cycle >/dev/null 2>&1 || true
  sleep 3
  udevadm settle >/dev/null 2>&1 || true
  resolve_block_vars
  if mount "$BYUUID" "$MNT" >/dev/null 2>&1 || mount "${PART:-}" "$MNT" >/dev/null 2>&1; then RES="SUCCESS"; else RES="NOPE"; fi
fi
say "RESULT: Palier 5 = $RES"

say "RESULT: ÉCHEC — non récupéré après tous les paliers."
exit 4
