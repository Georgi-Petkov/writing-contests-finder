# writing-contests-finder

A live, always-on list of inspirational-writing contests (English + Bulgarian) for quick scanning: dates, topic, prize, submission format, and whether previously-published work can be reused.

## Structure

- `live-site/` — the always-on project. An `azurerm_static_web_app` (Free SKU, verified $0-billing tier) serving `content/index.html`. Never destroyed between sessions.
- `data/contests.json` — the master contest list. Source of truth; committed for history.
- `scripts/refresh_contests.py` — searches for new/updated contests via the Claude API (web search + structured output), merges into `data/contests.json`, and regenerates `content/index.html`.
- `.github/workflows/refresh-contests.yml` — runs the refresh script weekly (and on demand via `workflow_dispatch`), commits the update, and redeploys the site.

## Manual refresh

```sh
export ANTHROPIC_API_KEY=...
python scripts/refresh_contests.py
```

## Fields per contest

- Name, language (EN/BG), topic/theme, prize, submission format
- Opens / deadline dates, computed status (Open / Upcoming / Closed)
- **Previously published OK?** — Yes / No / Unclear. Not a filter — an effort signal: "Yes" means an existing piece can be adapted, "No" means it needs to be written from scratch, "Unclear" means check the official rules before assuming either way.
