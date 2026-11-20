# CLIPFORGE – Mac-App

Lokale App für den Mac: überwacht freigegebene Twitch-Streamer, erkennt wichtige Momente
an **Chat-Spitzen** (Hauptsignal) und **Ton-Spitzen** (zweites Signal) und speichert
fertige TikTok-Clips: **genau 60 s, 9:16, Facecam oben, Gameplay unten, Hook, Untertitel**.
Zusätzlich holt sie die besten Momente aus **vergangenen Streams (VODs)**.

## Einrichtung (einmalig)
1. Terminal öffnen, Repo holen:  `git clone https://github.com/mom1627/CLIPFORGE.git && cd CLIPFORGE`
2. `./setup_mac.sh` (installiert FFmpeg, Python, Streamlink, yt-dlp, Whisper)
3. Twitch-Daten in `~/CLIPFORGE/.env` eintragen (nur für VODs nötig)

## Start
Doppelklick auf `start.command` (oder `./start.command`). Die Oberfläche öffnet sich unter
http://127.0.0.1:8787. Im Terminal steht zusätzlich ein Link mit Zugangscode für das **iPhone im selben WLAN**.

## So funktioniert es
- **Live:** Jede Minute wird geprüft, wer live ist. Live-Streamer werden automatisch aufgenommen
  (Puffer ~7 Min.) und der Chat mitgelesen (offizieller Twitch-Chat, nur lesen, anonym).
  Rastet der Chat aus (Standard: 2,5-fach so viel wie normal, Bots herausgefiltert), wird der Moment geschnitten.
- **VODs:** Button „Beste Momente aus den letzten Streams clippen“. Nutzt Chat-Stichproben
  (inoffizieller Twitch-Web-Zugang, vom Nutzer erlaubt; kann sich ändern) und lädt nur die 60-s-Stücke.
- **Clips:** liegen in `~/CLIPFORGE/clips/` und in der Oberfläche mit Vorschau, Download, Löschen.

## TikTok
- In https://developers.tiktok.com eine App anlegen, Produkte **Login Kit** und **Content Posting API** hinzufügen,
  Scope **video.upload** aktivieren, Redirect-URI `http://localhost:8787/tiktok/callback` eintragen.
- Client Key/Secret in `~/CLIPFORGE/.env` (`TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`), App neu starten.
- Oben rechts „Mit TikTok verbinden“ (am Mac, nicht am iPhone). Danach pro Clip „→ TikTok“ oder in den
  Einstellungen „Neue Clips automatisch zu TikTok“.
- Clips landen als **Entwurf in deiner TikTok-Inbox** (Benachrichtigung in der App). Dort Beschreibung/Sound setzen und posten.
  Direkt öffentlich posten erlaubt TikTok erst nach einer Prüfung (Audit) der App; vorher nur privat.

## Grenzen
- Facecam-Position je Streamer steht in `config/cams.json` (Anteile x,y,Breite,Höhe). Standard: unten rechts.
- Mac muss wach und online sein (`start.command` verhindert den Ruhezustand, solange die App läuft).
- Nur Streamer verwenden, deren Clips du nutzen darfst.
