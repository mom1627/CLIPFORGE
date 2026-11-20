#!/bin/bash
# CLIPFORGE – Komplett-Installation fuer den Mac (einmalig). Fragt einmal nach deinem Mac-Passwort (fuer Homebrew).
cd "$(dirname "$0")"
echo "== CLIPFORGE Installation =="
if ! command -v brew >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/brew ]; then
  echo "Installiere Homebrew (offizieller Installer, fragt nach deinem Mac-Passwort)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
grep -q "brew shellenv" ~/.zprofile 2>/dev/null || echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
./setup_mac.sh
echo
echo "Installation fertig. Starte die App jetzt mit Doppelklick auf start.command (oder: ./start.command)."
read -r -p "Enter zum Schließen …"
