#!/usr/bin/env bash
set -euo pipefail

# ---------- À PERSONNALISER ----------
CTRL="https://192.168.1.100:8443"   # ← ton contrôleur (autohébergé ⇒ :8443)
SITE="default"
USER="homeassistant"                # compte local SANS 2FA
PASS="homeassistant"
VERIFY_SSL="false"                   # autosigné ⇒ false
OUTDIR="/config/scripts/unifi"
# ------------------------------------

mkdir -p "$OUTDIR"
COOKIE="$OUTDIR/cookie.txt"
HDRS="$OUTDIR/headers.txt"
rm -f "$COOKIE" "$HDRS"

# Options cURL communes
CURL_BASE=(-sS -c "$COOKIE" -b "$COOKIE" -D "$HDRS" -H 'Accept: application/json')
[[ "$VERIFY_SSL" == "false" ]] && CURL_BASE+=(-k)

log(){ echo -e "\n>>> $*"; }

# --- 0) Page d'accueil (peuple parfois le cookie de session)
curl -I "${CURL_BASE[@]}" "$CTRL" >/dev/null || true

# --- 1) Récupérer le CSRF token (si dispo)
log "Récupération du CSRF…"
CSRF_JSON=$(curl "${CURL_BASE[@]}" "$CTRL/api/auth/csrf" || true)
# extraction sans jq :
CSRF=$(printf '%s' "$CSRF_JSON" | grep -oE '"csrf_token"\s*:\s*"[^"]+"' | sed -E 's/.*"([^"]+)".*/\1/' || true)
if [ -n "${CSRF:-}" ]; then
  echo "CSRF: $CSRF"
  HDR_CSRF=(-H "X-Csrf-Token: $CSRF")
else
  echo "Pas de CSRF renvoyé (ok sur certaines versions)."
  HDR_CSRF=()
fi

# --- 2) Login (v8+), fallback v6/v7
log "Login… (/api/login)"
  CODE=$(curl -o "$OUTDIR/login.json" -w '%{http_code}' \
    "${CURL_BASE[@]}" "${HDR_CSRF[@]}" \
    -H 'Content-Type: application/json' \
    -X POST -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" \
    "$CTRL/api/login" || true)
  echo "HTTP $CODE"

if [ "$CODE" != "200" ]; then
  echo "!! Échec de login. Vérifie USER/PASS (local), port :8443, et que 2FA est désactivée pour ce compte."
  exit 1
fi

# --- 3) Appels API authentifiés (en repassant le CSRF si on l’a)
log "Sites…"
curl "${CURL_BASE[@]}" "${HDR_CSRF[@]}" "$CTRL/api/self/sites" > "$OUTDIR/sites.json"
sed -n '1,80p' "$OUTDIR/sites.json"

echo -e "\nOK. Fichiers dans $OUTDIR :"
ls -1 "$OUTDIR"/{login.json,sites.json,sta.json,device.json}
