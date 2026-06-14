# APKHub — Architecture & Design Document

> **Mission.** Turn the fragmented experience of hunting for open-source Android apps across thousands of GitHub repositories into a single, organised, fast, and trustworthy catalogue — an *open-source Play Store* powered entirely by public GitHub releases.

This document covers the proposed solution, system architecture, implementation strategy, scalability model, security & compliance posture, deployment pipeline, and long-term maintenance plan.

---

## 1. The problem and the design thesis

Discovering an open-source Android application today is a scavenger hunt: you must know the project's name, find its repository, locate its **Releases** tab, dig through assets, pick the right APK architecture/variant, and only then download. There is no central index. Repositories are filed under inconsistent topics, release pages are unstructured, and asset filenames are ad-hoc (`app-debug.apk`, `linuxdroid-v4.2-signed.apk`, …).

**APKHub's thesis:** GitHub already *is* the world's largest open-source app store — it just lacks a catalogue layer. We add that layer **without re-hosting a single byte of binary**. The platform is a *metadata* product: it discovers, normalises, indexes, and links. Every download is a redirect to the canonical GitHub asset.

This thesis drives every architectural decision:

| Requirement | Architectural consequence |
|---|---|
| No redistribution, only linking | Static site + pointer metadata; no binary storage or CDN |
| Respect GitHub's policies | Conservative rate limiting, conditional requests, authenticated API |
| Hosted free on GitHub Pages | Static generation; data committed as JSON to the repo |
| Continuously fresh | Scheduled GitHub Actions indexer with incremental sync |
| Fast UX at scale | Client-side search index; pre-computed at build time |
| Trustworthy | Per-app attribution, license surface, direct official links |

---

## 2. Solution overview

APKHub is a **three-tier static architecture**:

1. **Indexer** (Python, runs in GitHub Actions) — the *write path*. Discovers repositories, harvests releases/assets, normalises metadata, persists ETags/timestamps for incremental sync, and writes structured JSON.
2. **Catalogue** (`app/data/*.json`, committed to the repo) — the *source of truth*. A flat, immutable, content-addressable dataset.
3. **PWA** (vanilla JS + service worker, served by GitHub Pages) — the *read path*. Renders the catalogue with instant search, filters, theming, favourites, and offline support.

Because the catalogue is plain JSON committed to a Git repo, the entire dataset is **versioned, diffable, auditable, and free to host**. There is no database server, no API gateway, and no per-request cost. This is the cheapest possible architecture that still satisfies all functional requirements.

```
                      ┌──────────────────────────────────────────────┐
                      │                 WRITE PATH                    │
                      │                                              │
   GitHub REST/GraphQL ◀───── indexer/index.py                        │
   (Search + Releases)        · topic/seed discovery                  │
                              · release + asset parsing (.apk)        │
                              · metadata normalisation                │
                              · ETag / incremental sync (state.json)  │
                              · license + category inference          │
                              · JSON-LD structured metadata           │
                              └──────────────┬───────────────────────┘
                                             │ git commit
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              CATALOGUE (JSON)                 │
                      │   app/data/apps.json   (summary index)        │
                      │   app/data/detail/*.json (full records)       │
                      │   app/data/state.json   (sync cursor / ETags) │
                      └──────────────┬───────────────────────────────┘
                                             │ served statically
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │                 READ PATH                     │
                      │   app/ (PWA on GitHub Pages)                  │
                      │   · client-side search (inverted index)       │
                      │   · filters, sort, categories                 │
                      │   · dark/light, favourites (localStorage)     │
                      │   · service worker offline cache              │
                      │   · links to official release assets          │
                      └──────────────────────────────────────────────┘
```

---

## 3. Detailed architecture

### 3.1 The Indexer (write path)

The indexer is the system's most complex component. It must be **correct, polite to GitHub, and resumable**. It is structured as a pipeline of pure-ish stages so each can be unit-tested in isolation.

#### 3.1.1 Discovery

Two complementary strategies feed the candidate set:

- **Seed repositories** (`config.toml`) — a curated allowlist of well-known FOSS Android projects. Guarantees baseline quality and survives search-index lag.
- **Topic search** — the GitHub Search API `/search/repositories?q=topic:android-app`, `topic:fdroid`, `topic:kotlin+android`, sorted by stars, paginated. Topics are far higher-precision than full-text search for binaries (which the Search API does not index anyway).
- **Release-asset scan** — for each candidate repo, fetch releases via **GraphQL** (batched, see below) and inspect `releaseAssets` for `.apk` extensions. A repo only "graduates" into the catalogue if it has at least one current APK release asset.

> **Why not `/search/code` for `.apk`?** Binary file contents are not indexed by code search, and releases live outside the default branch tree. Releases + assets is the authoritative surface.

#### 3.1.2 The GraphQL batch trick

Naïvely fetching releases per repo costs ~1 REST call/repo and explodes quickly. Instead we use the **GraphQL API** to fetch, in a single request, for up to ~50 repositories at once: `stargazerCount`, `description`, `licenseInfo`, `primaryLanguage`, `homepageUrl`, `repositoryTopics`, and the latest N releases each with their assets. This collapses dozens of REST calls into one node:

```graphql
query ($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Repository {
      nameWithOwner
      stargazerCount
      description
      licenseInfo { spdxId name }
      primaryLanguage { name }
      repositoryTopics(first: 20) { nodes { topic { name } } }
      releases(first: 5, orderBy: {field: CREATED_AT, direction: DESC}) {
        nodes {
          tagName publishedAt releaseAssets(first: 20) {
            nodes { name downloadUrl size contentType }
          }
        }
      }
    }
  }
}
```

This is the single most important scalability lever: **one request per ~50 repos** instead of 3–5 requests per repo.

#### 3.1.3 Asset parsing & APK intelligence

For each asset whose name ends in `.apk` (case-insensitive) **or** whose `contentType` is `application/vnd.android.package-archive`, we extract a record. Beyond the raw API fields, the indexer performs **filename heuristics** to enrich the catalogue:

- **Architecture** — `arm64-v8a`, `armeabi-v7a`, `x86_64`, `universal` substring match.
- **ABI splits / bundles** — detect `app-arm64-v8a-release.apk` style multi-APK releases and group them.
- **Variant** — `debug` vs `release`, flavour names (` foss`, ` foss`, `play`).
- **Version** — prefer the release tag; fall back to semver parsed from the filename.
- **Recommended asset** — when multiple APKs exist, recommend `universal`/`release` and fall back to `arm64-v8a` (the dominant Android ABI).

A future enhancement can **download the APK header only** (HTTP `Range: bytes=0-4095`) to read the real `AndroidManifest.xml` package name, version code, and `minSdkVersion` from the ZIP central directory — without fetching the full binary. This is cheap (~4 KB) and dramatically improves metadata fidelity. (Implemented behind a flag; off by default to stay within conservative bandwidth.)

#### 3.1.4 Metadata normalisation

Each candidate is normalised into a canonical record (the schema in §4). Normalisation includes:

- **Slug** — deterministic: `{owner}-{repo}` lowercased, ASCII-folded.
- **Category inference** — map known `repositoryTopics` and description keywords to a fixed taxonomy (`Tools`, `Media`, `Games`, `Communication`, `Productivity`, `Security`, `Development`, `Internet`, `System`, `Reading`, `Finance`, `Other`). Rule-based now; an embedding classifier later (§9).
- **Screenshots** — collect image URLs from the repo's `README` rendering (via the `contents`/`readme` API + lightweight markdown image regex) and from release body markdown. These are *referenced*, never copied.
- **License** — surface `licenseInfo.spdxId`; if `None` or `NOASSERTION`, flag the entry as **"license not declared"** and downgrade its search ranking.
- **Popularity score** — a blend so trending and evergreen apps both surface: `score = log10(stars+1) * recency_weight(days_since_push)`. Recency decays over ~180 days so a 5-year-old 10k-star project doesn't permanently dominate.

#### 3.1.5 Incremental sync & rate-limit politeness

This is what makes the platform sustainable as a long-running service rather than a one-shot scrape.

- **Conditional requests.** Every candidate repo fetch stores the response `ETag` / `Last-Modified` in `state.json`. On the next run we send `If-None-Match` / `If-Modified-Since`. A `304 Not Modified` costs **zero** against the rate limit and lets us skip re-processing. For a catalogue of 5,000 repos, the steady-state run becomes mostly `304`s.
- **Change-driven graduation.** We only re-harvest a repo's full release detail when the GraphQL `pushedAt` is newer than what we last saw. Otherwise the record is carried forward untouched.
- **Token bucket self-throttle.** The indexer reads the `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers after every request. It never exceeds a configurable fraction (default 80%) of the window and will **sleep until reset** rather than error out, then resume. Search endpoints (30 req/min authenticated) get their own limiter.
- **Exponential backoff** on `403`/`429`/`5xx` with jitter, capped at a few retries; failures are logged but never crash the run.
- **Resumability.** The candidate list and per-repo processing state are checkpointed to `state.json` after each page. If the Action is killed mid-run, the next run resumes.

#### 3.1.6 Output

The indexer writes three artefacts:

- `data/apps.json` — the summary array (everything the grid needs: name, owner, version, size, date, stars, score, category, license, color, icon, download URL, slug).
- `data/detail/{slug}.json` — full record per app (release notes, all assets/architectures, screenshots, topics, repo links, JSON-LD).
- `data/state.json` — ETags, last-seen `pushedAt`, last run timestamp, counts. **Not served** by Pages; lives in the repo for the next run. (Marked `noindex` / kept out of `app/` if you prefer to keep served paths clean — here it's stored at `indexer/state.json`.)

### 3.2 The Catalogue (data layer)

A deliberately boring, flat-file data store:

- **Why JSON, not SQLite/JSONL?** A single `apps.json` can be fetched with one HTTP request and parsed with `JSON.parse` — ideal for a cold client-side load. It's also trivially diffable in pull requests, which matters for an open, auditable catalogue.
- **Size budget.** At ~600 bytes per summary record, 5,000 apps ≈ 3 MB raw, ~400 KB gzipped. Comfortable. Beyond ~20k apps we shard by category initial (`data/a.json`, `data/b.json`, …) or move to a small SQLite + WASM (`sql.js`) for the read path. The schema doesn't change.
- **Immutability.** Records are append/upsert by slug. Deletions (repo taken private) are soft — we mark `archived: true` rather than purge, preserving bookmark integrity for users who favourited an app.

The canonical record schema is defined in §4.

### 3.3 The PWA (read path)

A dependency-light, framework-optional front end. The reference implementation is **vanilla JS + CSS custom properties** so it (a) has zero build step, (b) renders in restricted preview sandboxes, and (c) is trivially portable to React/Next.js later (the data contract is what matters, not the view layer).

Key subsystems:

- **Client-side search engine** (`app.js` `SearchIndex`). At load we build an **inverted index** over tokenised, lowercased, accent-folded text (name + owner + description + topics). Boolean-ish AND queries with prefix matching give instant results on tens of thousands of records with no network round trip. (For 100k+ records, swap in FlexSearch/MiniSearch; the API is identical.)
- **Filters & sorting.** Category, license family, primary language, "recently updated", and popularity are pure client-side predicates over the in-memory dataset. Sort keys: trending (score), stars, newest release, name.
- **State management.** A tiny store with `subscribe`. Views (grid, detail, favourites) re-render from derived state. History API gives shareable, deep-linkable detail URLs (`#/app/slug`) with proper back/forward and browser-resumable state.
- **Theming.** CSS variables driven by `prefers-color-scheme` + a manual toggle persisted in `localStorage`. One variable swap recolours the entire UI; no re-render.
- **Favourites/bookmarks.** Stored in `localStorage` as a slug set. Survives reloads; the Favourites view is a client filter over the set.
- **PWA & offline.** `manifest.webmanifest` makes it installable; a service worker (`sw.js`) precaches the shell (HTML/CSS/JS) and uses a **stale-while-revalidate** cache for `data/*.json`, so previously viewed content is available offline and updates appear on next visit. Network-first for the shell so users get UI fixes promptly.
- **Accessibility & performance.** Semantic HTML, keyboard navigable, lazy-loaded images (`loading="lazy"`), `content-visibility: auto` on cards for long lists, and virtualised rendering if list length grows past ~500 visible rows.

### 3.4 Structured data & SEO

Each detail view emits **JSON-LD `SoftwareApplication`** structured data, so search engines and Android's app-link indexers understand each entry:

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "...",
  "operatingSystem": "ANDROID",
  "applicationCategory": "...",
  "softwareVersion": "...",
  "author": { "@type": "Organization", "name": "...", "url": "..." },
  "license": "https://...",
  "downloadUrl": "https://github.com/.../releases/download/.../app.apk",
  "aggregateRating": { "@type": "AggregateRating", "ratingCount": ..., "ratingValue": 5 }
}
```

Because the catalogue is static HTML/JSON, it is crawlable as-is; the JSON-LD is the structured-metadata layer requested in the spec.

---

## 4. Data model (canonical record)

**Summary** (`apps.json[]`):

```jsonc
{
  "slug": "termux-termux-app",
  "name": "Termux",
  "owner": "termux",
  "ownerType": "Organization",
  "repo": "termux-app",
  "repoUrl": "https://github.com/termux/termux-app",
  "description": "Android terminal and Linux environment...",
  "icon": "https://.../icon.png",          // referenced, not hosted
  "color": "#000000",                       // derived dominant color for placeholder
  "category": "Tools",
  "topics": ["android", "terminal", "linux"],
  "language": "C++",
  "license": "GPL-3.0",
  "licenseDeclared": true,
  "version": "0.118.1",
  "versionCode": 1181,
  "minSdk": null,                            // from APK header parse when enabled
  "publishedAt": "2025-11-02T00:00:00Z",
  "size": 63180590,
  "downloadUrl": "https://github.com/.../app-v0.118.1.apk",
  "releasePage": "https://github.com/.../releases/tag/v0.118.1",
  "stars": 38200,
  "forks": 4100,
  "downloadCount": null,                    // present when GitHub exposes it
  "score": 62.4,                            // precomputed popularity score
  "recommendedAsset": { "arch": "universal", "abi": "arm64-v8a" },
  "screenshots": ["https://..."],           // referenced only
  "archived": false,
  "indexedAt": "2026-06-14T09:00:00Z"
}
```

**Detail** (`detail/{slug}.json`) adds: full `releaseNotes`, `changelog`, the complete `assets[]` array (every architecture/variant with size + URL), all `topics`, `homepageUrl`, `updatedAt`, and the JSON-LD block.

Versioning: a top-level `"$schema": "1"` lets the PWA and future migrations coexist. Additive changes only; breaking changes bump the major and ship a transform.

---

## 5. Implementation strategy

### 5.1 Phasing

**Phase 0 — Skeleton (delivered in this repo).** Static PWA + seed dataset + indexer core + scheduled Action wiring. Demonstrates the full loop on a curated set of ~12 known-good FOSS apps. Every UX feature works against seed data.

**Phase 1 — Scale discovery.** Topic search across all `android`-family topics, GraphQL batching on, ETag incremental sync. Target: ~1,000–3,000 apps. Introduce license/category inference quality gates.

**Phase 2 — Richness.** APK header parsing for real `minSdk`/`versionCode`/package name; README screenshot extraction; per-app JSON-LD detail pages pre-rendered for SEO.

**Phase 3 — Intelligence & accounts (opt-in, §9).** Embedding-based categorisation, recommendations, optional GitHub OAuth favourites sync, update-notification subscriptions (via a tiny Cloudflare Worker or GitHub Discussions webhook).

### 5.2 Engineering practices

- **Single source of truth for the schema** — a `schema.json`/Pydantic model used by both the indexer (serialise) and the PWA (a tiny validator in dev mode).
- **Deterministic output** — records sorted by slug, stable key order, so `git diff` is minimal and reviewable. Commits are auto-generated but human-auditable; egregious changes (mass deletions) fail a guard check.
- **CI checks** — `apps.json` schema validation, lint, and a "no binary committed" guard (`git diff --stat` rejecting any `.apk`).
- **Observability** — the Action prints a structured run summary (discovered, added, updated, 304s, rate-limit headroom, duration). Optionally posts to a status endpoint or a `data/_meta.json` file the PWA shows in an "Index health" footer.

### 5.3 Testing

- Unit tests for asset parsing, version/slug normalisation, category inference, scoring.
- Golden-file test: a fixture of real GraphQL/REST responses → expected `apps.json`.
- PWA: a small Playwright suite covering search, filter, theme toggle, favourites persistence, and offline (service-worker) load.

---

## 6. Scalability considerations

| Dimension | Strategy |
|---|---|
| **API budget** | GraphQL batching (~50 repos/req); conditional `304`s; self-throttle to 80% of window. 5,000 repos need only ~100 GraphQL requests in steady state. |
| **Catalogue size** | Flat JSON to ~20k apps (~1.6 MB gzipped). Beyond that, shard by category-letter or move read path to `sql.js`. Schema unchanged. |
| **Client performance** | Inverted index in Web Worker; virtualised list; `content-visibility`; lazy images. Linear scan of 20k records for filtering is <5 ms. |
| **Indexing wall-clock** | Horizontally shard the candidate space across **multiple Action matrix jobs** (by topic letter or a hash of repo id), each writing a shard file; a final job merges. Turns a 1-hour run into parallel ~10-minute runs. |
| **Freshness vs cost** | ETag incremental sync makes a daily run cheap; `304`s don't consume rate limit. Increase cadence on high-velocity repos, decrease on dormant ones. |
| **Storage** | Zero binary storage — the entire catalogue is metadata JSON in Git. GitHub's free Pages quota is effectively unlimited for this. |
| **Availability** | Static files on a CDN (GitHub Pages / Fastly). No server to scale or fail. Offline-first PWA means it works even during outages. |

The architecture is **horizontally parallel, mostly stateless, and embarrassingly cacheable** — the three properties that make a free-tier project scale to surprising size.

---

## 7. Security & compliance

This section is treated as a first-class requirement, not an afterthought, because a discovery platform sits at the intersection of third-party code, licensing, and user trust.

### 7.1 Scope & legal posture
- **Public data only.** The indexer authenticates for rate-limit headroom but never accesses private data; it operates strictly on public repos/releases.
- **No redistribution.** APKHub stores and serves **metadata only**. Every APK download is an HTTP redirect to the canonical `github.com/.../releases/download/...` asset owned by the upstream author. We never proxy, cache, or re-host binaries.
- **Attribution & licensing.** Each entry displays owner, repo URL, declared license (SPDX), and a link to the release page. Unlicensed projects are flagged. The project's own `LICENSE` covers the *catalogue code*; upstream licenses cover *the apps*.
- **No endorsement claim.** The UI clarifies that listing is automated and not an endorsement; users download at their own discretion.

### 7.2 Secret & token handling
- The `GITHUB_TOKEN` is injected by the Action as an environment variable, **never** committed, never logged. Requests that would echo it are scrubbed in logs.
- A dedicated fine-grained PAT (read-only, public repos) is preferred over a broad token; the Action's default `GITHUB_TOKEN` suffices for read access.
- The service worker and client never see any token — they consume static JSON only.

### 7.3 Supply-chain safety
- **"No binary committed" guard** — CI fails if any `.apk`/`.dex`/`.jar`/`.so` is added to the repo, enforcing the no-redistribution invariant mechanically.
- **Link integrity** — `downloadUrl`s are validated to be on `github.com`/`objects.githubusercontent.com` domains before publishing, preventing the catalogue from ever pointing at an attacker-controlled host.
- **Future malware scanning** (§9) — an integration stage can submit the asset URL (not the binary) to a scanning service or fetch the APK header for known-bad signature checks. Flagged entries are quarantined (`archived`/`flagged`) and hidden until reviewed.

### 7.4 Operational safety
- Rate-limit self-throttle prevents API bans (GitHub may throttle or suspend abusive tokens).
- All network calls have timeouts and bounded retries; a misbehaving upstream cannot wedge the Action.
- Structured logs exclude PII (there are no user accounts yet) and sensitive headers.

### 7.5 User-facing trust signals
- License badge, star count, last-updated date, and an explicit "Official source" link per app.
- "Index health" footer showing last successful run, app count, and rate-limit headroom — transparency about freshness.

---

## 8. Deployment process

### 8.1 Environments
- **Source of truth:** `main` branch on GitHub.
- **Indexing:** GitHub Actions, `schedule: cron: '0 */6 * * *'` (4×/day; tunable) plus `workflow_dispatch` for manual runs.
- **Hosting:** GitHub Pages, build = `app/` directory, served from the Action (Pages → "GitHub Actions" source).

### 8.2 The indexing workflow (`index.yml`) at a glance
1. Checkout (with the `state.json` from the previous run).
2. Install Python deps.
3. Run `indexer/index.py` → regenerates `app/data/*.json`.
4. **Guard checks:** schema validate; reject any binary; reject mass deletions.
5. Commit changed data back to `main` (bot identity).
6. Build/deploy `app/` to Pages.

### 8.3 Two deploy modes
- **Mode A (monorepo, simplest):** data commits trigger Pages redeploy. One repo, one Action. Recommended to start.
- **Mode B (data/site split):** a private `indexer` repo writes data to a public `site` repo via a cross-repo PAT or repository dispatch; the site repo only ever serves JSON + UI. Cleaner blast radius and lets the catalogue be public while indexing internals stay private.

### 8.4 Rollbacks
Because the catalogue is committed JSON, **rolling back is `git revert`**. No database snapshots, no migration anxiety. A bad index run is one commit to undo.

### 8.5 Custom domain & HTTPS
GitHub Pages supports custom domains with managed HTTPS. The PWA's `start_url` and manifest are configured for the final domain so installability and scope are correct.

---

## 9. Long-term maintenance plan

### 9.1 Freshness SLO
- Daily incremental index (cheap, ETag-driven).
- Weekly full re-scan of the candidate pool to catch repos GitHub's search index lags on.
- An `Index health` badge (last-run time, error rate) visible to maintainers and, optionally, users.

### 9.2 Sustainability
- **Zero marginal cost** in steady state — no servers, no DB, no CDN bill. The only quotas are GitHub API (generous for authenticated requests) and Actions minutes (free for public repos).
- **Human-in-the-loop for exceptions.** A maintainer workflow for quarantined/unlicensed/disputed entries lives in `.github/` issue templates + a `moderation.json` allow/deny list the indexer consults.

### 9.3 Roadmap of advanced enhancements (from the brief)
- **AI categorisation** — embed (name + description + topics) with a small model; cluster/classify into the taxonomy; beats keyword rules at long tail.
- **Automatic screenshot extraction** — parse README markdown images + Fastlane metadata (`fastlane/metadata/.../images/phoneScreenshots`) when present.
- **Malware/security scanning** — submit asset URL to VirusTotal/short hash to a local YARA rule set over the APK header; quarantine on hit.
- **Update notifications** — users subscribe to an app; a Worker diffs releases and emails/web-pushes on new versions.
- **Accounts & sync** — optional GitHub OAuth so favourites follow the user across devices; stored server-side in a tiny KV store (Cloudflare KV / Supabase).
- **Recommendation engine** — "apps like this" via collaborative or content-based similarity on the embedding space.
- **Popularity analytics dashboard** — historical stars/downloads over time (snapshotted daily into `data/_history.jsonl`).
- **Open-source rankings** — monthly leaderboards by category, growth rate, maintenance health.
- **i18n** — catalogue descriptions machine-translated; UI strings externalised.
- **Android companion app** — a thin native/TWA shell over the PWA with a `PackageManager` intent to install downloaded APKs and a background update checker.

### 9.4 Deprecation & data hygiene
- Soft-delete (`archived: true`) on repo deletion/privacy change; periodically prune entries archived >1 year with no inbound links.
- Schema migrations are additive with a versioned transform step in the indexer.

### 9.5 Community & governance
- Public repo, clear `CONTRIBUTING`, issue templates for "submit a repo" and "report a listing". The catalogue is auditable by design (every change is a Git diff), which is the strongest possible trust signal for an open app store.

---

## 10. Summary

APKHub realises the "open-source Play Store" by leaning into the constraints rather than fighting them: **no servers, no binaries, no redistribution** — just a disciplined metadata pipeline, a versioned JSON catalogue, and a fast offline-first PWA. The architecture is cheap, auditable, rollback-safe, and horizontally scalable exactly where it needs to be (parallel indexing) while remaining trivially cheap where it doesn't (read path). The result is a platform that turns GitHub's vast, fragmented release surface into a single trustworthy, searchable, installable catalogue.
