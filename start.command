#!/bin/bash
# Doppelklick im Finder startet CLIPFORGE und öffnet die Oberfläche im Browser.
cd "$(dirname "$0")"
PY="$HOME/CLIPFORGE/venv/bin/python"
[ -x "$PY" ] || { echo "Bitte zuerst ./setup_mac.sh ausführen."; read -r; exit 1; }
export PATH="$HOME/CLIPFORGE/venv/bin:$(brew --prefix 2>/dev/null)/bin:$PATH"
( sleep 2; open "http://127.0.0.1:8787" ) &
# --lan: auch vom iPhone im selben WLAN erreichbar (Link mit Zugangscode steht unten im Fenster)
caffeinate -i "$PY" app/server.py --lan
