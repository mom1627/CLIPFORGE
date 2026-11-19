# 15 TikTok-Reels – Produktionsauftrag für 20. November 2026

## Nutzerziel
15 **echte** 60,000-Sekunden-Reels aus englisch- und deutschsprachigen Twitch-Streamern (8 EN, 7 DE), vertikal 9:16 1080 × 1920, 30 fps, H.264/AAC, 3-Sekunden-Hook, echte zeitcodierte Untertitel, attraktive lustige/überraschende Szene. Nutzer postet selber; **keine automatische Veröffentlichung**.

**Status am 19.11.2026: 0/15 reale MP4s.** Kein Zugang zu 15 Ausgangsvideos in der vorliegenden Umgebung; Direkt-Downloads von Twitch nicht funktionierend. Kein echter Reel-Export darf als fertig ausgegeben werden.

## 15 Slots (Hook-Entwürfe – erst nach Sichtung freigeben)
| Slot | Kanal | Sprache | Vorläufige Hook |
|---|---|---|---|
| 01 | kaicenat | EN | Das hat niemand kommen sehen |
| 02 | kaicenat | EN | Warte auf seine Reaktion |
| 03 | kaicenat | EN | Der Chat war danach fertig |
| 04 | xqc | EN | Wie kann man so reagieren? |
| 05 | xqc | EN | Diese 60 Sekunden eskalieren komplett |
| 06 | ishowspeed | EN | Speed in seinem Element |
| 07 | ishowspeed | EN | Das Ende ist unbezahlbar |
| 08 | caseoh_ | EN | Dieser Moment ist unfassbar |
| 09 | montanablack88 | DE | Monte glaubt es selbst nicht |
| 10 | montanablack88 | DE | Was würde Monte jetzt sagen? |
| 11 | montanablack88 | DE | Warte auf Montes Reaktion |
| 12 | papaplatte | DE | Der Chat war sofort dabei |
| 13 | papaplatte | DE | Diese Szene wurde komplett wild |
| 14 | trymacs | DE | Trymacs hat damit nicht gerechnet |
| 15 | trymacs | DE | Das Ende setzt noch einen drauf |

## Bestehende Implementierungen
- Repo: https://github.com/mom1627/CLIPFORGE
- Cloudflare-Web-App: https://clipforge-live-free.hanoura1000.workers.dev
- GitHub: `scripts/live_capture.py`, Docker-Build, Colab-Notebook für manuelle Live-Aufnahme; noch kein erfolgreicher Livestream-MP4-Nachweis.
- Im Chat wurde ein **separates ZIP-Produktionspaket** erzeugt: `CLIPFORGE_15_Reels_Produktionspaket.zip`. Darin sind `render_reels.py` (60.000s FFmpeg-Reel mit Blur-Hintergrund und eingebrannten ASS-Untertiteln), `plan_15.csv`, README und Test. **Nicht im GitHub-Repository gespeichert.**
- Technischer Test mit **synthetischem** 62s Farbtestvideo erfolgreich: 540×960, 1800 Videoframes, **60.000000s** Ergebnis. Das ist ausdrücklich **kein echter Streamer-Clip**.

## Noch zu erledigen
1. Tatsächliche zugängliche Video-/VOD-Dateien der freigegebenen Streamer beschaffen; Rechte zum Aufzeichnen, Verarbeiten und Wiederveröffentlichen nach Nutzerangabe vorhanden, aber keine Twitch-Kanal-Editorrollen verifiziert.
2. Humor/Hook anhand der wirklichen Videos bewerten; keine erfundenen Szenen oder Untertitel.
3. Auf Originalsprache transkribieren; deutsche Übersetzungen englischer Clips bei Bedarf separat prüfen.
4. 15 echte MP4s auf 1080×1920, 30fps, 60.000s rendern; Qualitätsprüfung und Downloads bereitstellen.
5. Kein TikTok-Upload, Nutzer lädt selbst hoch.

## Grenzen
Cloudflare Workers Free transkodiert nicht dauerhaft 15 Videos mit FFmpeg. Twitch-Clip-Download-API gibt bei den fremden Kanälen 403 zurück. Google-Colab-Free-Laufzeiten können unterbrochen werden. Keine Zusage über fertige reale 15 Videos ohne nutzbare Quellaufnahmen.
