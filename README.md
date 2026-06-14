# APKHub — An Open-Source Play Store Powered by GitHub Releases

APKHub is a discovery engine that automatically scans **public** GitHub repositories and their release assets, indexes every `.apk` it finds, and presents them through a fast, modern, installable Progressive Web App hosted on GitHub Pages.

> **Philosophy:** Never redistribute binaries. Always link to the original, official GitHub release asset and attribute the upstream owner. APKHub is a *catalogue*, not a mirror.

---

## How it works (the 30-second version)

```
        ┌─────────────────────────┐      ┌──────────────────────────┐
        │   GitHub Actions cron    │      │   GitHub Pages (static)   │
        │   runs indexer/index.py  │      │   serves app/ (PWA)       │
        │   → respects rate limits │      │   → reads data/*.json     │
        │   → incremental ETag sync│      │   → client-side search    │
        └───────────┬─────────────┘      └────────────▲─────────────┘
                    │  commits data/*.json             │
                    └──────────────────────────────────┘
```

1. A **scheduled GitHub Action** runs a Python indexer.
2. The indexer queries the GitHub **Search API** + **GraphQL** to discover Android projects, fetches their releases/assets, filters for `.apk` files, normalises metadata, and writes JSON.
3. The committed JSON is served by **GitHub Pages**.
4. A static **PWA** renders the catalogue with instant client-side search, filters, dark/light mode, favourites, and offline caching.
5. Every "Download" button links to the **official** `github.com/.../releases/download/...` asset.

---

## Repository layout

```
.
├── README.md                  # You are here
├── DESIGN.md                  # Full architecture & design doc
├── LICENSE                    # MIT (the catalogue code); data respects upstream licenses
├── .github/workflows/
│   └── index.yml              # Scheduled + manual indexing job
├── indexer/
│   ├── index.py               # Discovery + indexing engine
│   ├── requirements.txt
│   └── config.toml            # Seed repos, topics, rate-limit policy
└── app/                       # The static PWA (deployed to Pages)
    ├── index.html
    ├── styles.css
    ├── app.js
    ├── manifest.webmanifest
    ├── sw.js                  # Service worker (offline cache)
    └── data/
        ├── apps.json          # Generated catalogue (committed by the Action)
        └── detail/*.json      # Per-app deep pages / structured metadata
```

---

## Quick start

### Preview the app locally
```bash
cd app
python3 -m http.server 8080
# open http://localhost:8080
```
The repository ships with a **seed dataset** (`app/data/apps.json`) so the UI is fully explorable with zero configuration.

### Run the indexer manually
```bash
pip install -r indexer/requirements.txt
export GITHUB_TOKEN=ghp_xxx        # optional but strongly recommended (5000 req/h vs 60)
python3 indexer/index.py --config indexer/config.toml --out app/data
```

### Deploy
1. Push to `main`.
2. Enable **Settings → Pages → GitHub Actions**.
3. The `index.yml` workflow both builds the data and deploys `app/` to Pages on a schedule.

See [`DESIGN.md`](DESIGN.md) for the full architecture, scalability model, security posture, and maintenance plan.
