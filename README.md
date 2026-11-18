# CLIPFORGE Free – Twitch Live-Clipper fürs iPhone

## Sofort testbarer 0-€-Weg ohne PC: Google Colab (iPhone)

**Wichtigster aktueller Testweg für echte MP4-Clips:** Das eigenständige Notebook [CLIPFORGE Gratis iPhone Colab](notebooks/CLIPFORGE_Gratis_iPhone_Colab.ipynb).

[**In Google Colab öffnen**](https://colab.research.google.com/github/mom1627/CLIPFORGE/blob/main/notebooks/CLIPFORGE_Gratis_iPhone_Colab.ipynb)

- Auf dem iPhone in Colab mit Google anmelden; bei **privatem** GitHub-Repository ggf. GitHub-Zugriff für Colab autorisieren oder die IPYNB über GitHub → Download in Colab importieren.
- Name des genehmigten Twitch-Streamers, kurze Aufnahmezeit (40–160 Sekunden), Clipdauer (15–60 Sekunden) und gewünschte Auflösung einstellen. Aufnahme- und Wiederverwendungsrechte bestätigen.
- **Laufzeit → Alle ausführen** wählen. Das Notebook installiert Streamlink, prüft den gerade laufenden öffentlichen Stream, nimmt einen Ausschnitt auf, wählt das lauteste Zeitfenster und rendert ein MP4.
- Das fertige 9:16-MP4 wird über den Dateidownload von Colab aufs iPhone angeboten (notfalls im linken Dateibrowser).
- **Grenzen:** Google Colab Free hat ungarantierte Kapazität/Laufzeiten; Twitch kann Cloud-IP-Zugriff blockieren. Aufnahme ist nur bei aktiver Colab-Sitzung möglich. Der Klick ist **manuell, keine 24/7-Automation**. Es ist noch **kein echter Livestream-Test** in Colab erfolgt. Bei Fehlern Ausgabe der Colab-Zellen prüfen.

---


Die kostenlose Cloud-Version der CLIPFORGE-App liegt direkt in diesem privaten Repository. Sie kann **laufende Twitch-Streams überwachen** und daraus **Twitch-Clips** erstellen, während dein PC ausgeschaltet ist.

## Funktionen

- Privates iPhone-Dashboard in Safari
- Watchlist mit bis zu 30 Twitch-Kanälen
- Livestatus und Zuschauerzahlen
- Twitch OAuth mit Scopes `clips:edit` und `editor:manage:clips`, automatische Token-Erneuerung
- Manuelles Clippen während eines laufenden Streams
- Automatisches Clippen per Cloudflare Cron (Prüfung alle 5 Minuten, voreingestellter Clip-Abstand: 20 Minuten)
- Twitch-Clip-Links und Statusanzeige
- Beliebte Twitch-Clips der letzten 7 Tage pro Streamer anzeigen (öffentliche Clip-Suche)
- MP4-Download über den offiziellen Twitch-Endpunkt **nur bei bestehender Kanalinhaber-/Editor-Berechtigung**
- Links zur Twitch-Clip-Bearbeitung bzw. zum Teilen anzeigen, soweit Twitch sie bereitstellt
- HMAC-geschützte Sitzung, Rate-Limit für falsche Admin-Passwörter, D1-Datenbank

**Aktueller Stand:** KI-Highlights auf Basis des Live-Videos, eigenständiges 9:16-Rendering, TikTok-Upload und automatische TikTok-Veröffentlichung sind **noch nicht enthalten**. Die Funktion erstellt derzeit neue Clips **zeitgesteuert**, nicht anhand erkannter besonders spannender Momente. Im Dashboard lassen sich außerdem populäre **öffentliche Clips der letzten 7 Tage** je Streamer entdecken und bei eigenen erfolgreich erstellten Clips offizielle MP4-Download-Links anfordern. **MP4-Download über die Twitch-API funktioniert nur für Kanalinhaber und offiziell eingetragene Editoren** (Scope `editor:manage:clips`). Ohne diese Twitch-Berechtigung werden keine MP4s ausgeliefert; auch die Freigabe zur Veröffentlichung auf TikTok ist separat zu beachten. Die Twitch-Oberfläche kann bei vom Streamer erlaubtem Teilen einen direkten TikTok-Export anbieten. Twitch-Links allein sind kein TikTok-Video.

## Kostenlos einrichten – alles am iPhone

### 1. Cloudflare und Datenbank

1. Erstelle einen kostenlosen Account unter https://dash.cloudflare.com.
2. Öffne **Workers & Pages → D1** und erstelle die D1-Datenbank **`clipforge-live`**.
3. Kopiere die angezeigte **Database ID** (UUID).
4. Öffne hier auf GitHub **`wrangler.toml`**, tippe auf **Edit** und ersetze `REPLACE_WITH_YOUR_D1_DATABASE_ID` durch die UUID. Speichere den Commit. **Die Database ID ist kein geheimes Passwort.**

### 2. GitHub auf Cloudflare verbinden

1. In Cloudflare **Workers & Pages → Create → Import repository** auswählen.
2. Verbinde GitHub und wähle **`mom1627/CLIPFORGE`**.
3. Als Deploy-Befehl **`npx wrangler deploy`** angeben (Working Directory: Root).
4. Wenn du den Namen auswählen musst: **`clipforge-live-free`**.
5. Nach der Veröffentlichung erhältst du die eigene URL, zum Beispiel `https://clipforge-live-free.DEIN-SUBDOMAIN.workers.dev`.

Die Namen der Menüpunkte können sich je nach Cloudflare-Version unterscheiden. Das Projekt benötigt **Node.js/Wrangler** für den Build; dein iPhone selbst muss kein Node.js installieren.

### 3. Geheimnisse sicher hinterlegen

Öffne in Cloudflare deinen Worker → **Settings → Variables and Secrets** und füge **vier Secrets** hinzu:

| Secret | Inhalt |
| --- | --- |
| `ADMIN_PIN` | Langes, selbst gewähltes Admin-Passwort; bitte mindestens 16 zufällige Zeichen |
| `SESSION_SECRET` | Ein **anderer** zufälliger Wert mit mindestens 32 Zeichen |
| `TWITCH_CLIENT_ID` | Twitch-App-Client-ID |
| `TWITCH_CLIENT_SECRET` | Twitch-App-Client-Secret |

Twitch-App erstellen: https://dev.twitch.tv/console/apps. App-Typ **Confidential**. Die Redirect URL muss auf die tatsächliche Worker-URL zeigen:

```
https://clipforge-live-free.DEIN-SUBDOMAIN.workers.dev/auth/callback
```

**Secrets niemals als GitHub-Dateien committen oder hier im Chat teilen.**

### 4. App auf dem iPhone starten

1. Worker-URL in **Safari** öffnen.
2. Mit `ADMIN_PIN` anmelden.
3. **Twitch verbinden** erneut auswählen und `clips:edit` sowie `editor:manage:clips` erlauben (die zweite Berechtigung ermöglicht Downloads **nur** für Kanäle, deren Inhaber bzw. Editor du bist).
4. Streamer zur Watchlist hinzufügen und bei Bedarf **Auto: AN** wählen.
5. Clips unter **Erstellte Twitch-Clips** ansehen. Dort stehen je nach Twitch-Freigabe **„MP4 anfordern“** und **„Twitch bearbeiten / teilen“** zur Verfügung. Für andere Kanäle nutze **„Clips der Woche“**, um vorhandene öffentliche Clips anzusehen; direkte TikTok-Freigabe hängt von den Einstellungen des Streamers ab.

Das geplante Clipping läuft anschließend in Cloudflare weiter, auch wenn dein iPhone nicht geöffnet ist. Cron-Aufrufe sind aber nicht auf die Sekunde genau und der kostenlose Tarif hat Nutzungslimits.

## Projektdateien

- `src/index.js`: Twitch OAuth, D1, API, Cron und Clip-Erstellung
- `public/index.html`: mobiles Dashboard
- `wrangler.toml`: Worker, Cron, D1 und statische Assets
- `tests/basic.test.js`: grundlegende Tests

### Entwicklung

```bash
npm install
npm test
npx wrangler dev
```

Für Live-Abfragen sind lokale D1-Bindings und passende Secrets erforderlich. Bei erstmaliger Nutzung erstellt die Anwendung ihre Tabellen selbst.

## Sicherheit und Kosten

- Das Repository sollte **privat** bleiben.
- Die öffentliche Worker-Adresse zeigt nur eine Login-Oberfläche; die API verlangt ein gültiges Sitzungscookie.
- Token und Einstellungen sind in Cloudflare gespeichert, nicht in GitHub.
- Der kostenlose Workers- und D1-Tarif kann diese leichte Steuerungs-App je nach Nutzung ermöglichen. Die App lädt **keine Videostreams herunter** und transkodiert keine Videos.
- Die laufende Verfügbarkeit hängt von Cloudflare-Limits, Twitch-API, Streamer-Einstellungen und gültiger OAuth-Verbindung ab.

Twitch-Dokumentation: https://dev.twitch.tv/docs/api/clips/  
Cloudflare Cron: https://developers.cloudflare.com/workers/configuration/cron-triggers/


---

## NEU: Live-Aufnahme → 9:16-MP4 → TikTok-Entwurf (separater Videorecorder)

Diese **zweite Komponente** erweitert die vorhandene Cloudflare-Web-App. Der kostenlose Cloudflare Worker kann keine aufwendige Videokodierung ausführen. Der bisherige Twitch-403-Fehler betrifft die Twitch-Clip-API. Mit ausdrücklicher Zustimmung und für öffentlich zugängliche Streams kann der neue Recorder alternativ mit Streamlink aufnehmen, ohne auf die Twitch-Clip-Download-API angewiesen zu sein. Er hebt **keine privaten oder DRM-Schutzmechanismen** auf.

**Stand:** Produktionscode vorbereitet, **noch kein dauerhafter Cloud-Server verbunden**. Es wurde noch kein echter Twitch-Stream durch diesen Recorder aufgenommen und kein Video an TikTok übertragen.

### Was der Recorder kann

1. Prüft die in `APPROVED_CHANNELS` explizit freigegebenen Streamer.
2. Prüft optional über die offizielle Twitch-API, ob sie `Grand Theft Auto VI` streamen. Ohne API-Zugang bleibt die Kategorie unbestätigt und der automatische TikTok-Upload wird zurückgehalten.
3. Nimmt pro Durchlauf einen kurzen Live-Abschnitt auf (standardmäßig 100 Sekunden).
4. Wählt ein circa 38 Sekunden langes Fenster anhand durchschnittlicher Audio-Lautstärke; das ist **noch keine inhaltliche KI-Erkennung**.
5. Erstellt mit FFmpeg ein H.264/AAC-MP4 im Hochformat 9:16 (standardmäßig 720 × 1280), mit vollständig sichtbarem Spielbild und unscharfem Hintergrund.
6. Speichert die MP4 auf dem ausführenden Server. Optional überträgt der offizielle TikTok-Upload-Adapter sie als **Inbox-Entwurf** auf das verbundene TikTok-Konto. Den Entwurf musst du in TikTok noch veröffentlichen.
7. Kann TikTok-Zugangstokens auf einem persistenten Server erneuern und den rotierenden Refresh-Token sicher lokal speichern.

### Entwicklungsprüfungen auf GitHub

`.github/workflows/live-capture.yml` ist ausschließlich ein manuell ausgelöster **Entwicklungs-/Funktionstest**. Ein separater CI-Workflow prüft Python und das MP4-Rendering mit einem **synthetischen Testvideo**. GitHub Actions wird **nicht** als Dauer-Video-Server verwendet, weil das mit den [GitHub Actions-Nutzungsbedingungen](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features) unvereinbar sein kann.

### Dauerbetrieb ohne deinen eigenen PC

Benötigt wird eine Linux-VM mit ungefähr 2 CPU-Kernen, 2 GB RAM, freiem Speicher und erlaubtem Docker-Betrieb. Ein Always-Free-VM-Angebot kann in Frage kommen, ist aber abhängig von Konto-, Zahlungs- und Kapazitätsvoraussetzungen. **Ein solches Hosting ist noch nicht angeschlossen**, daher läuft der MP4-Recorder noch nicht automatisch.

Auf dem Server:

```bash
git clone https://github.com/mom1627/CLIPFORGE.git
cd CLIPFORGE
cp .env.live.example .env.live
# .env.live privat bearbeiten
mkdir -p clipforge-data
sudo chown -R 10001:10001 clipforge-data
docker compose -f docker-compose.live.yml up -d --build
```

MP4s werden unter `clipforge-data/clips/` abgelegt. Der Daemon löscht ältere Videos nach 7 Tagen bzw. ab 2 GB Speicherbelegung. **Ein sicherer MP4-Download direkt im Cloudflare-iPhone-Dashboard ist noch nicht integriert.** Dafür ist eine zusätzliche private Videodatei-Anbindung nötig.

### Privater MP4-Download in der iPhone-Web-App (Cloudflare R2, optional)

Der Cloudflare-Worker enthält nun zwei neue, gegen unbefugten Zugriff geschützte Funktionen:

- `PUT /api/ingest`: nimmt MP4-Dateien nur mit einem 32+ Zeichen langen gemeinsamen Upload-Secret und passendem Dateinamen an und speichert sie in R2 (max. 60 MB).
- `GET /api/videos` und `GET /api/videos/{name}`: zeigen angemeldeten CLIPFORGE-Nutzern die Liste und liefern eine MP4 als Download, die direkt in Safari gesichert werden kann.

**Derzeit noch nicht aktiv:** Der R2-Bucket und das Secret müssen zuerst eingerichtet werden. Dafür in Cloudflare `Storage & Databases → R2` den privaten Bucket `clipforge-mp4` erstellen. **Achtung:** Die Aktivierung von R2 kann eine Zahlungsmethode verlangen; es gibt ein Freikontingent, aber kein garantiertes 0-€-Hosting über dessen Limits hinaus.

Nach Bucket-Erstellung das Worker-Binding mit Name `CLIPS_R2` auf `clipforge-mp4` legen und in der tatsächlich deployten `wrangler.toml` folgende Bindung ergänzen, damit das nächste GitHub-Deployment sie nicht verliert:

```toml
[[r2_buckets]]
binding = "CLIPS_R2"
bucket_name = "clipforge-mp4"
```

Als Cloudflare-Worker-Secret `CLIPFORGE_INGEST_SECRET` hinzufügen (einen eigenen zufälligen Wert mit 32+ Zeichen wählen) und **denselben Wert ausschließlich auf dem privaten Videorecorder** in `.env.live` eintragen. Dazu `CLIPFORGE_WORKER_URL=https://clipforge-live-free.hanoura1000.workers.dev` setzen. Secrets gehören nicht in GitHub. Nach erfolgreicher Übertragung erscheint das MP4 im Abschnitt `MP4-Clips & TikTok` deiner iPhone-Webseite. Lege in R2 eine Löschregel nach 7 Tagen fest, um den Speicherverbrauch zu begrenzen.


### TikTok richtig anschließen

Der Recorder verwendet den offiziellen TikTok Content Posting API-Endpunkt `video.upload`. Du brauchst eine eigene TikTok-Developer-Anwendung und die Autorisierung des **gewünschten TikTok-Kontos**. Für dauerhafte Nutzung sind `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` und `TIKTOK_REFRESH_TOKEN` erforderlich; ein kurzlebiger `TIKTOK_ACCESS_TOKEN` eignet sich nur für Tests. Diese Werte gehören nur in die Server-Konfiguration, niemals in GitHub.

**Inbox-Entwurf ist noch kein öffentlicher Post.** TikTok verlangt, dass du den Entwurf in der TikTok-App abschließend bearbeitest und veröffentlichst. Für vollautomatische öffentliche Posts ist eine geprüfte TikTok-Anwendung mit `video.publish`, korrekter Privatsphäre-Auswahl und Nutzereinwilligung nötig; das ist hier **noch nicht implementiert**.

Ein bereits an anderen Diensten angeschlossenes TikTok-Konto wird nicht automatisch verwendet. So landen GTA-Clips nicht versehentlich im falschen Markenprofil.

### Grenzen und Rechte

- Für fremde Streams sind Freigaben zum **Aufzeichnen, Bearbeiten und Wiederveröffentlichen** erforderlich; Twitch-Editorrechte und eine vertragliche Nutzungserlaubnis sind nicht dasselbe.
- Ein nicht öffentlich zugänglicher oder technisch gesperrter Stream wird nicht umgangen.
- Kurze Aufnahmen verpassen möglicherweise die Highlights, die außerhalb des Aufnahmefensters stattfinden.
- Der Daemon verarbeitet standardmäßig höchstens acht Clips pro Tag, mit zwei Stunden Abstand. Ein kostenloser 24/7-Dienst ist nicht garantiert.
- Für verwendete Musik und andere enthaltene Drittinhalte können weitere Rechte erforderlich sein.
