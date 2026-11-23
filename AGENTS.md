# CLIPFORGE – Anweisungen für Codex und andere Agenten

1. Lies zuerst **`HANDOFF_CODEX.md`** (vollständiger Stand, Pipeline, Kampagnen-Regeln, offene Punkte).
2. Danach **`CLAUDE.md`** (Projektregeln) und **`config/campaigns/*.json`** (Regeln je Kampagne).
3. Tests: `python3 -m unittest discover -s tests` – müssen grün bleiben.
4. Clips entstehen in GitHub Actions (`vod-clips.yml`, `monitor.yml`); die App liegt in `docs/` (GitHub Pages).
5. Keine Schlüssel/Tokens in Code, Repo, Logs oder Chat. Nutzer spricht Deutsch.
