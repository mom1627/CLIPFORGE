#!/bin/bash
# Doppelklick im Finder startet CLIPFORGE und öffnet die Oberfläche im Browser.
cd "$(dirname "$0")"
PY="$HOME/CLIPFORGE/venv/bin/python"
[ -x "$PY" ] || { echo "Bitte zuerst ./setup_mac.sh ausführen."; read -r; exit 1; }
export PATH="$HOME/CLIPFORGE/venv/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
command -v ffmpeg >/dev/null || { echo "FFmpeg fehlt – bitte ./setup_mac.sh erneut ausführen."; read -r; exit 1; }
"$PY" -c "import PIL" 2>/dev/null || { echo "Installiere Pillow für Untertitel…"; "$HOME/CLIPFORGE/venv/bin/pip" install -q Pillow; }
( sleep 2; open "http://127.0.0.1:8787" ) &
# --lan: auch vom iPhone im selben WLAN erreichbar (Link mit Zugangscode steht unten im Fenster)
caffeinate -i "$PY" app/server.py --lan
