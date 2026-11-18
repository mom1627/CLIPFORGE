# CLIPFORGE Free – Twitch Live-Clipper fürs iPhone

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
