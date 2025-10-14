#!/usr/bin/env bash
# Lecture légère: freq snapshot, power 0.5s, températures
R=/sys/class  GNU nano 7.2                                                  telemetry.sh                                                           
#!/usr/bin/env bash
# Telemetry légère (≈0.5 s) : freq snapshot, power 0.5s, températures (pkg+par cœur), CPU% (global+par cœur)
# Sans sudo. Robuste au formatage de `sensors`. Dynamique sur le nb de cœurs.

set -euo pipefail
export LC_ALL=C

# ---------- FREQ (snapshot, arrondi x10) ----------
FREQ_MHZ=$(
  awk '{s+=$1} END{mhz=(s/NR)/1000; printf "%d", int((mhz+5)/10)*10}' \
  /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo 0
)

# ---------- POWER (RAPL, moyenne 0.5 s, 1 décimale) ----------
R=/sys/class/powercap/intel-rapl:0
if [[ -r "$R/energy_uj" ]]; then
  E1=$(<"$R/energy_uj"); MAX=$(<"$R/max_energy_range_uj")
  sleep 0.5
  E2=$(<"$R/energy_uj")
  if (( E2 >= E1 )); then DIFF=$((E2-E1)); else DIFF=$(((MAX-E1)+E2)); fi
  POWER_W=$(awk -v uJ="$DIFF" 'BEGIN{printf "%.1f", uJ/1e6/0.5}')
else
  POWER_W="nan"
fi

# ---------- TEMPS via `sensors` (robuste au format) ----------
SENSORS_OUT="$(sensors 2>/dev/null || true)"

# helper: extrait le 1er nombre d'une ligne qui matche un motif
