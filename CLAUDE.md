# CLIPFORGE – Anweisungen für Claude Code

Lies zuerst `HANDOFF_CODEX.md` (vollständiger Stand, offene Punkte, Regeln). Kurzfassung:

- **Ziel:** Twitch-Streamer überwachen, Highlights (Chat- + Ton-Spitzen) als genau 60-s-Clips im 9:16-Layout
  (Facecam oben, Gameplay unten, Hook, Untertitel) schneiden und **automatisch öffentlich auf TikTok** posten
  (Konto `volta_ro`), max. ca. 15 Posts/24 h (TikTok-API-Grenze).
- **Mac-App:** `./start.command` → http://127.0.0.1:8787 (Code in `app/`, Pipeline in `scripts/`).
- **Posten (kostenlos):** `scripts/publisher.py` = Cloudinary (unsigned Upload, öffentlicher Link) + Buffer-API.
  Noch nicht mit echtem Konto getestet. Werte trägt der Nutzer selbst in der App ein (Bereich „Automatisch auf TikTok posten“).
- **Cloud (Mac aus):** GitHub Actions `.github/workflows/monitor.yml` (manuell starten oder `CLOUD_ALWAYS=on`).
  Privates Repo = 2000 Actions-Minuten/Monat. Nie gleichzeitig mit der Mac-App posten.
- **Tests:** `python3 -m unittest discover -s tests` – müssen grün bleiben.

## Regeln
- Keine Schlüssel/Tokens in Code, Repo, Logs oder Chat; `.env` bleibt lokal, Secrets trägt der Nutzer selbst ein.
- Keine Browser-Automation oder inoffiziellen Upload-APIs für tiktok.com.
- Nur Streamer aus der Freigabeliste. Nichts als fertig melden ohne Test mit echtem Clip.
- Nutzer spricht Deutsch, will kurze klare Schritte und immer den günstigsten Weg.
- Nach jeder größeren Änderung (Merge, neue Kampagne, Lauf-Ergebnis) den Stand in XMemo speichern:
  `update_state` mit `state_key: clipforge_active_task` (verifizierter Stand, Kampagnen, offene Punkte, nächster Schritt).
  Zu Beginn einer Sitzung diesen Stand zuerst lesen. Keine Schlüssel/Tokens speichern.
