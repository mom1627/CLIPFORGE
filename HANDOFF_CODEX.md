# CLIPFORGE – Übergabe (Stand 23.11.2026)

Lies diese Datei ganz, bevor du etwas änderst. Danach `CLAUDE.md` (Regeln) und `config/campaigns/*.json`.

## 1. Ziel

Twitch-/YouTube-Streamer überwachen, Highlights als **genau 60-s-Clips 9:16 (1080×1920)** schneiden:
oben **Webcam des Streamers**, unten Gameplay, weißer **Titel-Kasten** + roter **Zitat-Kasten** (echtes Zitat)
an der Naht, Untertitel. Clips werden für **Clipping-Kampagnen** (Content Rewards / Reach Clipping) gepostet;
der Nutzer lädt sie meist selbst hoch (TikTok `volta_ro`, Reels, Shorts, X) und reicht sie ein.
Nutzer spricht Deutsch, will kurze klare Schritte, günstigsten Weg, keine Schlüssel im Chat/Repo.

## 2. Wo läuft was

| Teil | Ort | Zweck |
|---|---|---|
| Cloud-Clips aus Aufzeichnungen | `.github/workflows/vod-clips.yml` → `scripts/vod_clips.py` | Hauptweg. Nur manuell starten. |
| Live-Monitor | `.github/workflows/monitor.yml` → `scripts/monitor.py` | alle 6 h automatisch (Repo ist öffentlich); postet nur bei Handstart mit `post=1` bzw. `AUTO_PUBLISH=1` |
| Handy-/Mac-App | `docs/` (GitHub Pages) → https://mom1627.github.io/CLIPFORGE/ | Clips ansehen, herunterladen (1080p), Beschreibung kopieren, „Heruntergeladen“-Markierung, lokal löschen |
| App-Pflege | `.github/workflows/app-update.yml` → `scripts/update_index.py` | Liste `docs/clips.json`, 540p-Vorschauen (Cloudinary), Clips löschen (`delete_files`, `delete_before`) |
| Mac-App (lokal) | `app/`, `./start.command` → http://127.0.0.1:8787 | alte lokale Oberfläche; Mac-Kopie ist ZIP ohne git |
| Clips (Dateien) | GitHub Release `clips` | MP4 + `clips.json` (Quell-Metadaten je VOD-Clip) |
| Debug-Standbilder | Release `debug` | 16:9-Vollbilder je Clip (Facecam-Position prüfen) |

Repo ist **öffentlich** (unbegrenzte Actions-Minuten). Secrets/Variablen in GitHub: `TWITCH_CLIENT_ID/SECRET`,
`BUFFER_API_KEY` (Secret), `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_UPLOAD_PRESET` (= `clipforge`, unsigned), `AUTO_PUBLISH`,
`APPROVED_CHANNELS`, `ALLOWED_GAMES`. Niemals Werte ins Repo schreiben.

## 3. vod-clips.yml – Eingaben

- `campaign` – Name aus `config/campaigns/` (`clipup`, `lacy`, `dylanpage`, `bendadonnn`); leer = keine Kampagne
- `streamers` – Twitch-Logins (sonst Kampagnen-Kanäle bzw. Freigabeliste)
- `hours` (≤168), `max_clips` (≤12), `title_filter`
- `vod_url` – direkte Aufzeichnung (z. B. YouTube); **YouTube blockiert GitHub-Server** („Sign in to confirm you're not a bot“) → nur am Mac
- `redo_files` – vorhandene Clips aus dem Original-Stream **neu schneiden** (Quelle aus `clips.json`; Live-Clips `clipforge_<kanal>_<zeit>.mp4` werden über die Twitch-VOD-Zeit gefunden, ±20 s)
- Concurrency: eigene Warteschlange pro Kampagne und für `redo` (sonst ersetzt GitHub wartende Läufe).

Beispiel: `campaign=clipup, max_clips=8, hours=120, title_filter=""`.

## 4. Pipeline (vod_clips.produce) – Reihenfolge der Prüfungen

1. Kandidaten: Twitch-Chat-Spitzen (`chat_probe.py`, inoffizieller GQL-Endpunkt, vom Nutzer erlaubt) bzw. YouTube-„Meistgesehen“-Heatmap, sonst Audio-Spitzen. Stream-Anfang (15 min) übersprungen.
2. **Spiel-Kapitel**: Bei `game` in der Kampagne nur Momente im Twitch-Kapitel „Grand Theft Auto VI“; ohne Kapitel nur, wenn VOD-Titel „GTA“ enthält.
3. Schon vorhandene oder ausgeblendete Clips (`docs/hidden.json`) werden nicht erneut geschnitten.
4. **Webcam**: `config/cams.json` (von Hand: lacy, kaicenat, …) sonst **automatisch** `scripts/facecam.py` (OpenCV-Haar frontal+Profil in voller Auflösung, stabile Position in ≥2 von 8 Bildern). **Ohne Webcam kein Clip** (`REQUIRE_FACECAM=1` in beiden Workflows, `need_facecam` in Kampagnen). NudeNet ist dafür ungeeignet (verkleinert auf 320 px).
5. Layout (`live_capture.render_vertical`): Facecam max. 2× vergrößert, deblock+hqdn3d+cas, unscharfer Rand; Gameplay 4:5 unten (Kampagne `focus: creator` → Facecam 40 %).
6. Whisper-Untertitel; Kampagne `require_words` / `reject_words` prüfen (gesprochener Text).
7. Overlay (`captions.build_overlay_frames`, Pillow): Titel (`pick_hook`: Kampagnen-`title`/`titles` oder Vorlagen mit Anzeigenamen `DISPLAY`), Zitat (`pick_quote`, Schimpfwort-Filter nur mit `clean_quotes`), Logo (`campaign.paste_logo`), Untertitel über dem Logo. **Keine Emojis im Video** (Schrift kann sie nicht), in der Beschreibung schon.
8. Endkodierung CRF 17 (Zwischenschritt CRF 10), ffprobe-Prüfung 60,0 s / 1800 Frames.
9. **Gameplay-Prüfung** `scripts/gameplay_check.py` (Bewegung ≥ 6, kein großes Gesicht im Spielbereich), **Nacktheits-Filter** `scripts/safety.py` (NudeNet, an 17 echten Clips eingestellt).
10. Upload ins Release, `clips.json` ergänzen, App-Liste aktualisieren (Push mit fetch+reset+`--merge`, konfliktfrei).

## 5. Kampagnen (config/campaigns/*.json) – Regeln

**clipup** – ClipUp GTA VI, $0.30/1000 Views (nur US/UK/CA/AU; IG 30 %), ab 3.000 Views/Clip, max $150/Clip.
Offizielles Logo `config/campaign/logo.png` **unten rechts, 50 % Breite, ganzen Clip sichtbar, nie verdeckt/verändert**
(wie Beispiel im Google-Doc). `#gta6 #Clipup`. Nur GTA-Gameplay von Streamern, **Lacy ausgeschlossen** (eigene Kampagne),
Webcam Pflicht, Posts 60 Tage online, keine fremden Wasserzeichen. Regeln: Google-Doc in `rules`.

**lacy** – Reach Clipping, $12.5K Pool, Lacys GTA-Marathon ab 18.11.2026. **Kein Logo**, `#LACY` + Lacys Name,
Lacy im Fokus (Facecam 40 %, Webcam Pflicht), **nicht negativ** (neutrale `titles`), kein Hate-Farming,
Publikum ≥50 % englischsprachig, nur TikTok/Reels/Shorts/X, keine Collabs/Bots, eigene Thumbnails.
Jeder Clip ≥500 Views, insgesamt 750K für Auszahlung.

**dylanpage** – Dylan Page GTA-Marathon (YouTube `ylNDsCWeWGI`). Kein Logo, `#DylanPage`, alles Englisch,
Dylan immer im Fokus, keine irreführenden Titel (fester `title`), keine KI-Bilder/-Stimmen, eigene Edits.
**Nur am Mac möglich** (YouTube blockt Cloud): `CAMPAIGN=dylanpage CLIPFORGE_LOCAL=1 VOD_URL=… venv/bin/python scripts/vod_clips.py`.

**bendadonnn** – BenDaDonnn x Puffco GTA 6. Nur Bens Puffco-GTA-Stream; Puffco muss vorkommen (`require_words`),
**kein Glücksspiel** (`reject_words`), positiv, Webcam Pflicht. Twitch-Login `bendadonnn` **ungeprüft**.
Risiko: Cannabis-Inhalte verstoßen gegen TikTok/IG-Richtlinien → Nutzer gewarnt (eigenes Konto empfohlen).

Neue Kampagne = neue JSON-Datei; Felder: `channels`, `exclude`, `logo`, `logo_pos`, `logo_width`, `hashtags`, `game`,
`language`, `need_facecam`, `focus`, `title`/`titles`, `require_words`, `reject_words`, `clean_quotes`, `rules`.

## 6. Handy-App (docs/)

`index.html` (ohne Build), `clips.json` (von `update_index.py`), `hidden.json` (ausgeblendet), `manifest.json`, `icon.png`.
Videos spielen über Cloudinary-Vorschauen (GitHub-Release-Dateien spielt Safari nicht ab). Beschreibung je Clip
wird passend zur Kampagne erzeugt (`fix_captions`, Lacy → `#LACY`). Echtes Löschen nur über `app-update.yml`.

## 7. Bekannte Grenzen / offene Punkte

- Facecam-Qualität hängt an der Quelle (Lacys Kamera filmt das Zimmer → Gesicht ~80 px). KI-Upscaling bewusst **nicht** eingebaut (Dylan-Regel verbietet KI-Material).
- Gameplay-Prüfung lässt scrollenden Abspann/Browser durch → manchmal von Hand ausblenden.
- Live-Monitor-Clips haben keine Quell-Metadaten (Neuschnitt nur über Zeit-Zuordnung).
- Buffer-Autoposting technisch fertig, aber `AUTO_PUBLISH` stand auf 0; nie mit echtem Konto bestätigt.
- BenDaDonnn-Kanalname prüfen; erster Lauf steht aus.
- Prüfe neue Clips immer per Standbild-Leiste (alle 10–12 s) auf: Webcam oben, GTA-Gameplay, Logo nur bei ClipUp.

## 7a. Qualitätsregeln (seit 26.11.2026, nach Nutzer-Beschwerde)

- **Nur GTA VI**: Live-Monitor `STRICT_GAME=Grand Theft Auto VI` (unbekannte Kategorie = nein), Kategorie wird direkt
  vor jedem Schnitt erneut geprüft (Wechsel zu Just Chatting → kein Clip). VOD: ohne Twitch-Kapitel reicht der Titel
  nur noch bei Einzel-Kampagnen (Lacy, Dylan, Ben), nicht bei ClipUp (Hasan-Fall).
- **Platzierung**: Facecam braucht Gesicht in ≥4 von 8 Bildern; fertiger Clip muss oben in ≥40 % der Bilder ein
  Gesicht haben (`gameplay_check.cam_check`) und unten Gameplay ohne großes Gesicht (`full_check`), in beiden Pipelines.
- **Hooks**: Zitat-Hook nur als ganzer Satz (Satzanfang nach . ? !, Ende auf . ? !, kein Ende auf „in a“ usw.),
  sonst Vorlage. `QUOTE_HOOKS=0` schaltet Zitat-Hooks ganz ab.
- **App**: nur die besten `KEEP_BEST=3` Clips der letzten 24 h (Rang: Reaktion `quality`, dann Score); der Rest wird
  aus dem Release gelöscht. Live-Clips erscheinen **sofort** (`scripts/app_sync.py` nach jedem Upload).

## 8. Arbeitsweise (bitte einhalten)

- Branch → PR → mergen; Tests `python3 -m unittest discover -s tests` müssen grün sein (Stand: 78+).
- Workflow-Tests laufen mit `CAMPAIGN=` (leer).
- Nichts als fertig melden ohne echten Lauf + Sichtprüfung.
- Keine Browser-Automation/inoffiziellen Upload-APIs für TikTok; keine Umgehung von YouTube-Bot-Schutz.
- Nach größeren Änderungen Stand in XMemo `clipforge_active_task` speichern (siehe CLAUDE.md).
