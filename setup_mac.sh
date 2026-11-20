#!/bin/bash
# CLIPFORGE – einmalige Einrichtung auf dem Mac (Apple Silicon oder Intel)
set -e
cd "$(dirname "$0")"
echo "== CLIPFORGE Einrichtung =="
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew fehlt. Installiere es zuerst (Anleitung: https://brew.sh), dann dieses Skript erneut starten."
  exit 1
fi
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
PY="$(brew --prefix)/bin/python3.12"
HOME_DIR="$HOME/CLIPFORGE"
mkdir -p "$HOME_DIR"
[ -d "$HOME_DIR/venv" ] || "$PY" -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install --upgrade pip -q
"$HOME_DIR/venv/bin/pip" install -q -r app/requirements.txt
if [ ! -f "$HOME_DIR/.env" ]; then
  cat > "$HOME_DIR/.env" <<'ENV'
# Twitch-App-Zugang (https://dev.twitch.tv/console/apps). Nur fuer VOD-Clips noetig.
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
# TikTok-App (https://developers.tiktok.com): Produkte Login Kit + Content Posting API, Scope video.upload
# Redirect-URI: http://localhost:8787/tiktok/callback
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
# OmniSocials-API-Schlüssel (öffentlich auf TikTok posten): https://app.omnisocials.com/settings/api
OMNISOCIALS_API_KEY=
ENV
  chmod 600 "$HOME_DIR/.env"
fi
echo "Lade Whisper-Modell (einmalig, ~500 MB)…"
"$HOME_DIR/venv/bin/python" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" || echo "Whisper-Modell später erneut versuchen."
echo
echo "Fertig. Trage deine Twitch-Daten in $HOME_DIR/.env ein und starte die App mit:  ./start.command"
