# CLIPFORGE – Übergabe an Codex (Stand 20.11.2026, 18:40)

## Ziel
Eine App, die auf Mohamads MacBook Air (M-Chip, macOS) läuft, freigegebene Twitch-Streamer überwacht,
wichtige Momente (Chat-Spitzen + Ton-Spitzen) live und aus vergangenen Streams (VODs) clippt,
fertige TikTok-Clips baut (genau 60 s, 9:16, oben Facecam, unten Gameplay, Hook + Untertitel)
und sie **automatisch auf TikTok veröffentlicht** (Konto „volta_ro“/„Voltrao“).

## Repo
`github.com/mom1627/CLIPFORGE` (privat), Branch `main`. Mac-Kopie liegt unter `~/CLIPFORGE`
(aus ZIP, kein git). Start: `cd ~/CLIPFORGE && ./start.command` → http://127.0.0.1:8787.
iPhone im WLAN: Link mit `?k=<code>` steht im Terminal (Code ändert sich bei jedem Start).
Laufzeitdaten: `~/CLIPFORGE/clips/` (MP4 + JSON je Clip), `~/CLIPFORGE/config.json`,
`~/CLIPFORGE/.env` (Twitch/TikTok-Schlüssel, NICHT ins Repo), `~/CLIPFORGE/tiktok_token.json`, `~/CLIPFORGE/venv`.

## Was funktioniert (geprüft)
| Teil | Datei | Status |
|---|---|---|
| Mac-Installation (Homebrew, ffmpeg, Python 3.12 venv, streamlink, yt-dlp, faster-whisper) | `install_mac.command`, `setup_mac.sh`, `start.command` | läuft auf dem Mac |
| Lokale Web-App mit Streamerliste, Live-Status, Clip-Galerie, Download, Einstellungen | `app/server.py`, `app/manager.py`, `app/static/index.html` | läuft |
| Live-Chat mitlesen (offizieller Twitch-IRC, anonym), Bot-Filter, Chat-Spitzen | `app/chat.py` | läuft, Tests in `tests/test_app.py` |
| Live-Aufnahme in 30-s-Segmenten, Ton-Spitzen, 60-s-Clip-Schnitt | `app/live.py`, `scripts/monitor.py` | läuft, bis 6 Streams parallel; ~40 echte Clips erzeugt |
| Layout Facecam oben / Gameplay unten, Facecam-Position je Streamer | `scripts/live_capture.py::render_vertical(cam_box, fit)`, `POST /api/cam` | läuft; Positionen gesetzt für ohnepixel, ishowspeed, djmariio, cohhcarnage, auronplay(keine) |
| VOD-Clips (schnelle Chat-Stichproben über inoffiziellen gql.twitch.tv, vom Nutzer erlaubt) | `scripts/vod_clips.py`, `scripts/chat_probe.py` | läuft auf GitHub Actions (~8 Min); lokal braucht `.env` TWITCH_CLIENT_ID/SECRET (fehlen noch auf dem Mac) |
| TikTok Login (OAuth, Desktop Login Kit, PKCE als Hex-SHA256) | `app/tiktok.py` | **verbunden** (Sandbox-App „clipforg“, Sandbox „clipforge-mac“, Target User volta_ro) |
| TikTok Upload als Entwurf (Content Posting API, Scope `video.upload`, Inbox) | `app/tiktok.py::upload_draft` | 1 Clip erfolgreich angekommen |

## Offene Probleme
1. ~~**Hook/Untertitel fehlen in Mac-Clips.**~~ **Gelöst 21.11.:** ohne libass zeichnet `captions.py` Hook/Untertitel mit Pillow (PNG + concat + `overlay`), Test `tests/test_captions_overlay.py`. Auf dem Mac einmal `./setup_mac.sh` bzw. `venv/bin/pip install Pillow` nötig. Ursprünglich: Homebrew-ffmpeg hat kein libass → Filter `ass=` schlägt fehl
   („Error parsing filter description“). Lösung: Untertitel/Hook mit Pillow als transparente PNGs rendern und per
   `overlay=enable='between(t,a,b)'` einbrennen (overlay ist immer vorhanden). Pillow in `app/requirements.txt` ergänzen.
   Datei: `scripts/captions.py::add_captions`.
2. **TikTok-Upload-Sperre** `spam_risk_too_many_pending_share`: Zu viele unbearbeitete API-Uploads in 24 h.
   Löst sich nach 24 h oder wenn der Nutzer die Inbox-Benachrichtigung öffnet und postet.
3. **Automatisch öffentlich posten (eigentliches Ziel) ist mit der eigenen TikTok-App nicht erreichbar:**
   - Ohne Audit: Direct Post nur `SELF_ONLY`, Konto muss privat sein.
   - Audit wird laut TikTok Content Sharing Guidelines abgelehnt für: Inhalte von anderen Plattformen kopieren,
     private/interne Tools für eigene Konten, nicht-originale Inhalte. CLIPFORGE erfüllt alle drei.
     Quelle: https://developers.tiktok.com/doc/content-sharing-guidelines
   - TikTok Studio im Browser: CSP von tiktok.com blockiert das Laden von localhost-Dateien; Datei-Dialog nicht automatisierbar.
   - **Nicht machen:** Browser-Automation/Bots, die tiktok.com bedienen, oder inoffizielle Upload-APIs.
     Verstößt gegen die TikTok-Nutzungsbedingungen und gefährdet das Konto.
4. Facecam-Position wird pro Streamer von Hand eingetragen; Gesichtserkennung wäre besser.
5. Alte Clips vor 18:27 haben falschen oberen Ausschnitt (vor Facecam-Einstellung entstanden).

## Erlaubte Wege zum Ziel „automatisch posten“
- **A (geht jetzt):** Entwurf + 1 Tipp am Handy. Pro Clip ~10 s Handarbeit.
- **B (empfohlen prüfen):** Einen **offiziell freigegebenen Social-Media-Planer** mit TikTok-Direct-Post anbinden
  (z. B. OmniSocials-API, Buffer, Later o. Ä. – deren TikTok-Apps sind bereits geprüft). CLIPFORGE lädt den fertigen
  Clip per deren API hoch und plant den Post. Vorher prüfen: Preis, ob API-Upload von Videos erlaubt ist,
  und ob deren Regeln das Posten fremder Streamer-Clips erlauben (Erlaubnis der Streamer liegt laut Nutzer vor).
- **C:** TikTok-Audit nur, wenn das Produkt ehrlich in eine zulässige Form passt (z. B. Tool für Streamer,
  die ihre **eigenen** Streams clippen). Für das aktuelle Konzept nicht realistisch.

## Update 20.11. 19:00 – Weg B eingebaut (OmniSocials)
- `scripts/publisher.py`: Upload (base64) + `posts/create-and-publish` als TikTok-Reel, öffentlich, mit Beschreibung/Hashtags. Tests: `tests/test_publisher.py` (Fake-Server). **Gegen echtes OmniSocials noch nicht getestet** (API-Key fehlt).
- Mac-App: Knopf „Veröffentlichen“ je Clip (Beschreibung editierbar), Einstellung „automatisch öffentlich posten“ + max. Posts/Tag + Hashtags.
- GitHub `monitor.yml`: Secret `OMNISOCIALS_API_KEY`, Variablen `AUTO_PUBLISH=1`, `MAX_POSTS`, `CAPTION_TAGS`; Zeitplan alle 6 h, läuft bei privatem Repo nur mit Variable `CLOUD_ALWAYS=on` (verbraucht Minuten).
- Doppelte Posts vermeiden: Wenn die Mac-App läuft, GitHub-Workflow „Live-Monitor“ deaktivieren (oder CLOUD_ALWAYS aus).

## Nächste Schritte (Reihenfolge)
1. ~~Untertitel-Fix mit Pillow~~ erledigt; noch mit echtem Live-Clip auf dem Mac prüfen.
2. Weg B prüfen und, falls passend, Planer-API in `app/manager.py` als zweites Ziel neben `upload_tiktok` einbauen
   (Einstellung „Automatisch posten: aus / TikTok-Entwurf / Planer“), max. 3–5 Posts pro Tag, Abstand ≥ 2 h.
3. Twitch-Schlüssel in `~/CLIPFORGE/.env` eintragen lassen (Nutzer), dann VOD-Knopf testen.
4. Clip-Ranking: nur die besten Clips posten (Chat-Stärke, Ton, Dauer der Spitze).

## Regeln für die Weiterarbeit
- Keine Schlüssel/Tokens ins Repo oder in Logs. `.env` bleibt lokal.
- Nichts als fertig melden ohne Test mit echtem Clip.
- Nur Streamer aus der Freigabeliste; keine Umgehung von TikTok-/Twitch-Regeln.
- Tests: `python3 -m unittest discover -s tests` (alle grün, Stand 37+).

## Update 21.11. – Buffer statt OmniSocials (kostenlos)
- Nutzer will nichts bezahlen und möglichst viele Posts. **TikTok erlaubt über APIs ca. 15 Posts pro Konto in 24 h** (für alle Tools zusammen). Ziel daher: 15/Tag, ein Konto.
- `scripts/publisher.py` ist jetzt: Clip per **unsigned Upload zu Cloudinary** (kostenlos, kein Geheimnis) → öffentlicher HTTPS-Link → **Buffer GraphQL `createPost`** (`https://api.buffer.com`, Bearer-Key, `mode: customScheduled`, `dueAt` = jetzt + 3 min) für den TikTok-Kanal. Buffer hat keine Upload-API, braucht direkten öffentlichen Link (Doku: developers.buffer.com/guides/hosting-media.html).
- Einstellungen: `BUFFER_API_KEY` (geheim), `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_UPLOAD_PRESET`, optional `BUFFER_CHANNEL_ID`. Mac-App: Bereich „Automatisch auf TikTok posten“ → schreibt in `~/CLIPFORGE/.env` (nur von localhost, Schlüssel wird nie zurückgegeben) und prüft, ob ein TikTok-Kanal gefunden wird.
- Automatik (`Manager._auto_post_tick`, jede Minute): postet den stärksten ungeposteten Clip der letzten 12 h, max. `max_posts_per_day` (Standard 15, rollierend 24 h), Mindestabstand `post_gap_minutes` (Standard 60).
- GitHub `monitor.yml`: Secret `BUFFER_API_KEY`, Variablen `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_UPLOAD_PRESET`, `MAX_POSTS` (pro Lauf, Standard 4; Läufe alle 6 h ≈ 16/Tag), `POST_GAP_MINUTES`.
- **Noch nicht gegen echtes Buffer/Cloudinary getestet** (nur Fake-Server, `tests/test_publisher.py`, `tests/test_autopost.py`). Offen: prüfen, ob Buffer Free TikTok-Videoposts per API annimmt und wie viele geplante Posts der Free-Tarif gleichzeitig erlaubt; Cloudinary-Free-Kontingent (Speicher) im Blick behalten, alte Videos dort löschen.
- OmniSocials ist entfernt (kostenpflichtig).

## Update 21.11. (abends) – Cloud postet am Ende die besten 5
- `monitor.py` postet nicht mehr sofort. Jeder Clip bekommt `score` (dB über normalem Pegel, `Detector.strength`), Bericht `output/monitor_report.json` wird laufend geschrieben.
- Neuer Schritt in `monitor.yml` „Beste Clips posten“ (`scripts/post_best.py`, `if: always()`): nur Clips mit genau 60 s, Nacktheits-Filter (`scripts/safety.py`, NudeNet, 1 Standbild/s ganz + Gameplay-Ausschnitt; Brust ab 0,7 in 2 Bildern, Intimbereich 1 Treffer; Po zählt nicht; fehlt NudeNet → nichts posten. Geprüft an 17 echten Clips: 17/17 richtig, Lauf 44929781759), Top `POST_BEST` (5) nach Score, Abstand `POST_GAP_MINUTES` (60). Ohne `AUTO_PUBLISH=1` nur Vorschau im Log.
- Bugfix: `monitor.py` benutzte `publisher` ohne Import (Absturz bei AUTO_PUBLISH=1).
- 60-s-Fix: Bei Lücke in der Aufnahme rutscht der Start nach vorn (`clip_offset`), sonst kein Clip. Die alten 50-s-Clips stammen aus Läufen vor Commit 0b38936.
- `nsfw-check.yml`: prüft alle Release-Clips mit dem Filter (manuell startbar).
