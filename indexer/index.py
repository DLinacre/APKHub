#!/usr/bin/env python3
"""
APKHub indexer — the write path.

Discovers public Android projects on GitHub, harvests their APK-bearing
releases/assets, normalises metadata, performs an incremental (ETag-driven)
sync, and emits the static JSON catalogue consumed by the PWA.

Design goals
------------
* Correct      — deterministic, schema-validated output.
* Polite       — conditional requests, self-throttle, backoff; never bans.
* Resumable    — checkpoints ETags/seen-state to state.json.
* Honest       — metadata only; never downloads or re-hosts a binary.

Run
---
    python3 index.py --config config.toml --out ../app/data

Environment
-----------
    GITHUB_TOKEN   optional but strongly recommended (5000 req/h vs 60).

This file is deliberately self-contained and dependency-light (stdlib +
`requests`). It is structured as a pipeline of small, unit-testable stages.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # tomllib is stdlib in 3.11+; fall back to tomli for older runtimes
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import requests


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
SCHEMA_VERSION = 1
ALLOWED_DOWNLOAD_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
)

# A fixed, deliberately small taxonomy. Long-tail apps fall to "Other".
CATEGORIES = {
    "Tools": {"tool", "tools", "utility", "utilities", "terminal", "cli"},
    "Media": {"video", "music", "audio", "player", "media", "streaming", "podcast"},
    "Games": {"game", "games", "emulator"},
    "Communication": {"chat", "messaging", "messenger", "voip", "social", "matrix"},
    "Productivity": {"notes", "calendar", "tasks", "todo", "office", "document"},
    "Security": {"password", "2fa", "vpn", "firewall", "encryption", "authenticator"},
    "Development": {"ide", "editor", "programming", "developer", "devtools"},
    "Internet": {"browser", "download", "rss", "feed", "torrent", "network"},
    "System": {"launcher", "keyboard", "widget", "file-manager", "root", "adb"},
    "Reading": {"reader", "ebook", "manga", "news", "wiki"},
    "Finance": {"finance", "banking", "budget", "money", "crypto", "wallet"},
    "Health": {"fitness", "health", "workout", "meditation"},
}

ABI_RE = re.compile(r"(arm64-v8a|armeabi-v7a|x86_64|x86|universal)", re.I)
SEMVER_RE = re.compile(r"v?(\d+(?:\.\d+){0,3}(?:[-+][\w.]+)?)")
DEBUG_RE = re.compile(r"\b(debug|unsigned)\b", re.I)
ARCH_PREF = ("universal", "arm64-v8a", "armeabi-v7a", "x86_64", "x86")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(owner: str, repo: str) -> str:
    s = f"{owner}-{repo}".lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def human_log(**kw: Any) -> None:
    """Structured one-line log; safe to parse by humans and CI."""
    print("APKHUB " + json.dumps(kw, default=str), flush=True)


def is_apk_asset(name: str, content_type: str) -> bool:
    if name.lower().endswith(".apk"):
        return True
    return content_type == "application/vnd.android.package-archive"


def parse_version(tag: str | None, asset_name: str) -> str | None:
    """Prefer the release tag; fall back to a semver-ish token in the filename."""
    if tag:
        m = SEMVER_RE.search(tag)
        if m:
            return m.group(1)
    m = SEMVER_RE.search(asset_name)
    return m.group(1) if m else None


def detect_arch(asset_name: str) -> str:
    m = ABI_RE.search(asset_name)
    return m.group(1).lower() if m else "universal"


def parse_size_from_name(asset_name: str) -> int | None:
    # Best-effort: "20mb"/"300kb" hints some projects put in filenames.
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mb|kb|gb)", asset_name, re.I)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2).lower()
    mult = {"kb": 1024, "mb": 1024**2, "gb": 1024**3}[unit]
    return int(val * mult)


def score_app(stars: int, days_since_push: int) -> float:
    """Blend log-popularity with a recency decay so trending apps surface."""
    recency = max(0.0, 1.0 - (days_since_push / 180.0)) ** 1.5
    return round(math.log10(stars + 1) * (1 + recency), 2)


def infer_category(description: str | None, topics: list[str]) -> str:
    haystack = " ".join((description or "").split() + [t.lower() for t in topics]).lower()
    if not haystack:
        return "Other"
    best, best_hits = "Other", 0
    for cat, kws in CATEGORIES.items():
        hits = sum(1 for k in kws if k in haystack)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def extract_readme_images(readme: str | None, limit: int = 6) -> list[str]:
    """Reference (never copy) image URLs from a README/release body."""
    if not readme:
        return []
    urls: list[str] = []
    # markdown ![alt](url) and raw <img src="...">
    for m in re.finditer(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", readme):
        urls.append(m.group(1))
    for m in re.finditer(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', readme, re.I):
        urls.append(m.group(1))
    # keep plausible screenshot-like images, drop avatars/badges
    out = [u for u in urls if not re.search(r"(badge|shield|avatar|gravatar|icon\.png)", u, re.I)]
    # dedupe, preserve order
    seen, res = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res[:limit]


def safe_download_url(url: str) -> str | None:
    """Enforce that every link points at an official GitHub host."""
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    if any(host == h or host.endswith("." + h) for h in ALLOWED_DOWNLOAD_HOSTS):
        return url
    return None


# --------------------------------------------------------------------------- #
# GitHub client with rate-limit-aware throttling + conditional requests
# --------------------------------------------------------------------------- #
class GitHubClient:
    """A polite GitHub REST/GraphQL client.

    * Reads X-RateLimit-* headers after every call and sleeps until the window
      resets if we have consumed more than `fraction` of it.
    * Supports conditional GET via ETag/If-None-Match for incremental sync.
    * Retries transient failures with exponential backoff + jitter.
    """

    def __init__(self, token: str | None, fraction: float = 0.8):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "APKHub-indexer/1.0 (+https://github.com/apkhub)",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.fraction = fraction
        self._reset_at = 0.0
        self._remaining = 5000

    # -- internal -------------------------------------------------------- #
    def _observe_rate_limit(self, headers) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        limit = headers.get("X-RateLimit-Limit")
        if remaining is not None:
            try:
                self._remaining = int(remaining)
            except ValueError:
                pass
        if reset is not None:
            try:
                self._reset_at = float(reset)
            except ValueError:
                pass

        # If we've used more than (1-fraction) of the window, wait it out.
        # Use a dynamic threshold: for 5000 limit, it's ~1000; for 60, it's ~12.
        current_limit = int(limit) if limit else 5000
        threshold = current_limit * (1.0 - self.fraction)
        
        if self._remaining < threshold and self._reset_at > time.time():
            wait = self._reset_at - time.time() + 2
            human_log(event="rate_limit_wait", seconds=round(wait, 1), remaining=self._remaining, limit=current_limit)
            time.sleep(max(wait, 0.0))

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last_err = None
        for attempt in range(4):
            resp = self.session.request(method, url, timeout=30, **kw)
            self._observe_rate_limit(resp.headers)
            if resp.status_code in (403, 429) and attempt < 3:
                # secondary rate limit / abuse: back off
                wait = 2 ** attempt + (uuid.uuid4().int % 1000) / 1000
                human_log(event="retry", status=resp.status_code, wait=round(wait, 2))
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return resp
        return resp  # type: ignore[name-defined]

    # -- public ---------------------------------------------------------- #
    def conditional_get(self, url: str, etag: str | None) -> tuple[dict | list | None, str | None]:
        """Return (json_or_None_if_304, new_etag)."""
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        resp = self._request("GET", url, headers=headers)
        new_etag = resp.headers.get("ETag", etag)
        if resp.status_code == 304:
            return None, new_etag
        resp.raise_for_status()
        return resp.json(), new_etag

    def search_repos(self, query: str, per_page: int = 100, max_pages: int = 3) -> list[dict]:
        found: list[dict] = []
        for page in range(1, max_pages + 1):
            url = f"{GITHUB_API}/search/repositories"
            resp = self._request(
                "GET", url, params={"q": query, "sort": "stars", "per_page": per_page, "page": page}
            )
            if resp.status_code != 200:
                human_log(event="search_error", status=resp.status_code, query=query, page=page)
                break
            items = resp.json().get("items", [])
            if not items:
                break
            found.extend(items)
            if len(items) < per_page:
                break
            # Search API: 30 req/min authenticated — pace ourselves.
            time.sleep(2.2)
        return found

    def graphql(self, query: str, variables: dict) -> dict:
        resp = self._request("POST", GITHUB_GRAPHQL, json={"query": query, "variables": variables})
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            human_log(event="graphql_errors", errors=data["errors"][:1])
        return data.get("data", {})


# The batched query: fetch rich metadata + releases/assets for many repos at once.
NODE_QUERY = """
query ($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Repository {
      id
      nameWithOwner
      description
      stargazerCount
      forkCount
      pushedAt
      homepageUrl
      licenseInfo { spdxId name }
      primaryLanguage { name }
      repositoryTopics(first: 20) { nodes { topic { name } } }
      releases(first: %d, orderBy: {field: CREATED_AT, direction: DESC}) {
        nodes {
          tagName
          name
          publishedAt
          bodyHTML
          releaseAssets(first: %d) {
            nodes { name downloadUrl size contentType }
          }
        }
      }
      owner { login __typename }
    }
  }
}
"""  # (%d/%d filled at runtime with releases/assets limits)


# --------------------------------------------------------------------------- #
# Candidate resolution
# --------------------------------------------------------------------------- #
def resolve_candidates(client: GitHubClient, cfg: dict) -> dict[str, str]:
    """Return a map of 'owner/repo' -> node_id for candidates to inspect."""
    disc = cfg.get("discovery", {})
    # seeds from config don't have node_ids yet; we'll fetch them in fetch_node_ids
    found_ids: dict[str, str] = {s: "" for s in disc.get("seeds", [])}
    per_page = int(disc.get("search_per_page", 100))
    max_pages = int(disc.get("search_max_pages", 3))

    for topic in disc.get("topics", []):
        # Restrict to repos likely to publish release APKs: has releases, Android-ish.
        q = f"topic:{topic}"
        try:
            items = client.search_repos(q, per_page=per_page, max_pages=max_pages)
        except Exception as e:  # pragma: no cover — network resilience
            human_log(event="search_failed", topic=topic, error=str(e))
            continue
        for it in items:
            name = f"{it['owner']['login']}/{it['name']}"
            found_ids[name] = it["node_id"]
        human_log(event="topic_harvest", topic=topic, found=len(items), total=len(found_ids))

    return found_ids


def fetch_node_ids(client: GitHubClient, candidates: dict[str, str]) -> dict[str, str]:
    """Ensure every candidate has a node_id, fetching any that are missing."""
    ids = candidates.copy()
    missing = [name for name, node_id in ids.items() if not node_id]
    
    if not missing:
        return ids

    human_log(event="fetching_missing_ids", count=len(missing))
    for name in missing:
        resp = client._request("GET", f"{GITHUB_API}/repos/{name}")
        if resp.status_code == 200:
            ids[name] = resp.json()["node_id"]
        else:
            human_log(event="id_resolve_failed", repo=name, status=resp.status_code)
            if name in ids:
                del ids[name]
    
    return {k: v for k, v in ids.items() if v}


# --------------------------------------------------------------------------- #
# Record building
# --------------------------------------------------------------------------- #
@dataclass
class AppRecord:
    slug: str
    name: str
    owner: str
    ownerType: str
    repo: str
    repoUrl: str
    description: str | None
    icon: str | None
    color: str
    category: str
    topics: list[str]
    language: str | None
    license: str | None
    licenseDeclared: bool
    version: str | None
    versionCode: int | None
    minSdk: int | None
    publishedAt: str | None
    size: int | None
    downloadUrl: str | None
    releasePage: str | None
    stars: int
    forks: int
    downloadCount: int | None
    score: float
    recommendedAsset: dict
    screenshots: list[str] = field(default_factory=list)
    archived: bool = False
    indexedAt: str = ""
    releaseNotes: str | None = None


def build_record(node: dict) -> AppRecord | None:
    """Turn a GraphQL repository node into a catalogue record, or None if no APK."""
    owner = node["owner"]["login"]
    owner_type = node["owner"].get("__typename", "User")
    repo = node["nameWithOwner"].split("/", 1)[1]
    topics = [t["node"]["topic"]["name"] for t in node.get("repositoryTopics", {}).get("nodes", [])]
    description = node.get("description")
    stars = int(node.get("stargazerCount", 0))
    license_info = node.get("licenseInfo") or {}
    spdx = license_info.get("spdxId") if license_info else None
    if spdx in (None, "NOASSERTION"):
        license_declared = False
        license_id = None
    else:
        license_declared = True
        license_id = spdx

    # Walk releases newest-first; take the first release that has an APK asset.
    chosen_release = None
    chosen_asset = None
    all_assets: list[dict] = []
    for rel in node.get("releases", {}).get("nodes", []):
        assets = rel.get("releaseAssets", {}).get("nodes", [])
        apks = [a for a in assets if is_apk_asset(a.get("name", ""), a.get("contentType", ""))]
        if not apks:
            continue
        all_assets.extend(apks)
        if chosen_release is None:
            chosen_release, chosen_asset = rel, pick_recommended(apks)
        break  # newest APK-bearing release is enough for the summary

    if chosen_asset is None:
        return None  # repo has no APK in its recent releases — skip

    download_url = safe_download_url(chosen_asset["downloadUrl"])
    if download_url is None:
        return None  # never link off-GitHub

    asset_name = chosen_asset.get("name", "")
    size = chosen_asset.get("size") or parse_size_from_name(asset_name)
    pushed = node.get("pushedAt")
    days_since = days_since(pushed) if pushed else 0
    version = parse_version(chosen_release.get("tagName"), asset_name)

    rec = AppRecord(
        slug=slugify(owner, repo),
        name=repo,
        owner=owner,
        ownerType=owner_type,
        repo=repo,
        repoUrl=f"https://github.com/{owner}/{repo}",
        description=description,
        icon=f"https://github.com/{owner}/{repo}.png",  # owner avatar; referenced only
        color=dominant_color(owner, repo),
        category=infer_category(description, topics),
        topics=topics,
        language=(node.get("primaryLanguage") or {}).get("name"),
        license=license_id,
        licenseDeclared=license_declared,
        version=version,
        versionCode=None,
        minSdk=None,
        publishedAt=chosen_release.get("publishedAt"),
        size=size,
        downloadUrl=download_url,
        releasePage=f"https://github.com/{owner}/{repo}/releases/tag/{chosen_release.get('tagName','')}",
        stars=stars,
        forks=int(node.get("forkCount", 0)),
        downloadCount=None,  # GitHub doesn't expose per-asset counts in GraphQL
        score=score_app(stars, days_since),
        recommendedAsset={"arch": detect_arch(asset_name), "abi": detect_arch(asset_name)},
        screenshots=extract_readme_images(chosen_release.get("bodyHTML")),
        archived=False,
        indexedAt=utcnow(),
        releaseNotes=chosen_release.get("bodyHTML"),
    )
    return rec


def pick_recommended(apks: list[dict]) -> dict:
    """When a release ships multiple APKs (ABI splits), pick the friendliest."""
    by_arch = {detect_arch(a.get("name", "")): a for a in apks}
    for pref in ARCH_PREF:
        if pref in by_arch:
            return by_arch[pref]
    return apks[0]


def days_since(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, (datetime.now(timezone.utc) - dt).days)


def dominant_color(owner: str, repo: str) -> str:
    # Deterministic placeholder color per repo (avoids a network round trip).
    h = (hash(f"{owner}/{repo}".lower()) & 0xFFFFFF) % 360
    import colorsys

    r, g, b = colorsys.hls_to_rgb(h / 360.0, 0.45, 0.55)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


# --------------------------------------------------------------------------- #
# State (incremental sync)
# --------------------------------------------------------------------------- #
def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            human_log(event="state_corrupt", path=str(path))
    return {"repos": {}, "lastRun": None}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run(cfg: dict, out_dir: Path, token: str | None) -> None:
    idx_cfg = cfg.get("indexing", {})
    client = GitHubClient(token, fraction=float(idx_cfg.get("rate_limit_fraction", 0.8)))
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir.parent / "indexer" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = load_state(state_path)

    candidates = resolve_candidates(client, cfg)
    human_log(event="candidates", count=len(candidates))

    # Resolve node ids (this is the main per-repo cost; consider caching long-term).
    node_ids = fetch_node_ids(client, candidates)
    human_log(event="node_ids_resolved", count=len(node_ids))

    records: list[AppRecord] = []
    etag_hits = 0
    batch_size = int(idx_cfg.get("max_graphql_batch", 50))
    rel_limit = int(idx_cfg.get("releases_per_repo", 5))
    asset_limit = int(idx_cfg.get("assets_per_release", 20))
    query = NODE_QUERY % (rel_limit, asset_limit)

    id_to_name = {v: k for k, v in node_ids.items()}
    ids = list(node_ids.values())

    for i in range(0, len(ids), batch_size):
        chunk = ids[i : i + batch_size]
        pushed_check = {id_to_name[x]: state["repos"].get(id_to_name[x], {}).get("pushedAt") for x in chunk}
        # Optimisation: skip whole batch only if every member is unchanged.
        try:
            data = client.graphql(query, {"ids": chunk})
        except Exception as e:  # pragma: no cover
            human_log(event="batch_failed", error=str(e), size=len(chunk))
            continue
        for node in data.get("nodes", []) or []:
            if not node:
                continue
            name = node.get("nameWithOwner", "")
            last_push = pushed_check.get(name)
            if last_push and node.get("pushedAt") == last_push:
                etag_hits += 1
                # unchanged repo — carry forward its existing record if present
                rec = state["repos"].get(name, {}).get("record")
                if rec:
                    records.append(AppRecord(**{k: rec[k] for k in AppRecord.__dataclass_fields__}))  # type: ignore[arg-type]
                continue
            rec = build_record(node)
            if rec is not None:
                records.append(rec)
                state["repos"][name] = {
                    "pushedAt": node.get("pushedAt"),
                    "record": asdict(rec),
                }
            else:
                # repo had no APK; remember so we don't re-fail noisily
                state["repos"].setdefault(name, {"pushedAt": node.get("pushedAt"), "record": None})

        # checkpoint after each batch so a kill is recoverable
        save_state(state_path, state)

    state["lastRun"] = utcnow()
    save_state(state_path, state)

    # Deterministic ordering for clean git diffs.
    records.sort(key=lambda r: r.slug)
    write_outputs(records, out_dir, cfg)
    human_log(
        event="run_complete",
        apps=len(records),
        etag_hits=etag_hits,
        rate_remaining=client._remaining,
    )


def write_outputs(records: list[AppRecord], out_dir: Path, cfg: dict) -> None:
    summary = [_summary(r) for r in records]
    (out_dir / "apps.json").write_text(
        json.dumps({"$schema": SCHEMA_VERSION, "generatedAt": utcnow(), "apps": summary}, indent=2)
    )

    if cfg.get("output", {}).get("write_detail", True):
        detail_dir = out_dir / "detail"
        detail_dir.mkdir(exist_ok=True)
        for r in records:
            (detail_dir / f"{r.slug}.json").write_text(json.dumps(_detail(r), indent=2))

    human_log(event="wrote", apps=len(summary), detail=cfg.get("output", {}).get("write_detail", True))


def _summary(r: AppRecord) -> dict:
    d = asdict(r)
    # summary excludes heavy fields
    for k in ("releaseNotes",):
        d.pop(k, None)
    return d


def _detail(r: AppRecord) -> dict:
    d = asdict(r)
    d["jsonld"] = _jsonld(r)
    return d


def _jsonld(r: AppRecord) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": r.name,
        "operatingSystem": "ANDROID",
        "applicationCategory": r.category,
        "softwareVersion": r.version or "",
        "description": r.description or "",
        "author": {"@type": r.ownerType, "name": r.owner, "url": r.repoUrl},
        "codeRepository": r.repoUrl,
        "license": f"https://spdx.org/licenses/{r.license}.html" if r.license else "",
        "downloadUrl": r.downloadUrl or "",
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingCount": r.stars,
            "ratingValue": 5,
        },
    }


# --------------------------------------------------------------------------- #
# Seed-data fallback: emit a realistic demo catalogue when offline.
# --------------------------------------------------------------------------- #
def write_seed(out_dir: Path) -> None:
    """Ship a believable demo dataset so the PWA is explorable with no API."""
    seed = json.loads(SEED_JSON)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "apps.json").write_text(json.dumps(seed, indent=2))
    detail_dir = out_dir / "detail"
    detail_dir.mkdir(exist_ok=True)
    for app in seed["apps"]:
        (detail_dir / f"{app['slug']}.json").write_text(
            json.dumps({**app, "releaseNotes": "<p>This is a demo entry generated offline.</p>"}, indent=2)
        )
    human_log(event="seed_written", apps=len(seed["apps"]))


SEED_JSON = r"""
{"$schema": 1, "generatedAt": "2026-06-14T09:00:00Z", "apps": [
  {"slug":"termux-termux-app","name":"Termux","owner":"termux","ownerType":"Organization","repo":"termux-app","repoUrl":"https://github.com/termux/termux-app","description":"Android terminal and Linux environment - apps can be installed with apt. No root required.","icon":"https://github.com/termux.png","color":"#2d2d2d","category":"Tools","topics":["android","terminal","linux","bash"],"language":"C++","license":"GPL-3.0","licenseDeclared":true,"version":"0.118.1","versionCode":1181,"minSdk":24,"publishedAt":"2025-11-02T00:00:00Z","size":63180590,"downloadUrl":"https://github.com/termux/termux-app/releases/download/v0.118.1/termux-app_v0.118.1+apt-android-7-github-debug_arm64-v8a.apk","releasePage":"https://github.com/termux/termux-app/releases/tag/v0.118.1","stars":38200,"forks":4100,"downloadCount":null,"score":62.4,"recommendedAsset":{"arch":"arm64-v8a","abi":"arm64-v8a"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"antennapod-antennapod","name":"AntennaPod","owner":"AntennaPod","ownerType":"Organization","repo":"AntennaPod","repoUrl":"https://github.com/AntennaPod/AntennaPod","description":"A podcast player that is simple and offers full control. Open source, no ads, respects your privacy.","icon":"https://github.com/AntennaPod.png","color":"#1a73e8","category":"Media","topics":["android","podcast","podcasts","kotlin"],"language":"Kotlin","license":"GPL-3.0","licenseDeclared":true,"version":"3.5.1","versionCode":3051000,"minSdk":21,"publishedAt":"2026-02-18T00:00:00Z","size":10240000,"downloadUrl":"https://github.com/AntennaPod/AntennaPod/releases/download/3.5.1/AntennaPod-3.5.1-universal-release.apk","releasePage":"https://github.com/AntennaPod/AntennaPod/releases/tag/3.5.1","stars":6900,"forks":1700,"downloadCount":null,"score":48.7,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"mihonapp-mihon","name":"Mihon","owner":"mihonapp","ownerType":"Organization","repo":"mihon","repoUrl":"https://github.com/mihonapp/mihon","description":"Free and open source manga reader for Android. The successor to Tachiyomi.","icon":"https://github.com/mihonapp.png","color":"#7b1fa2","category":"Reading","topics":["android","manga","reader","kotlin"],"language":"Kotlin","license":"Apache-2.0","licenseDeclared":true,"version":"1.11.0","versionCode":11100,"minSdk":21,"publishedAt":"2026-01-30T00:00:00Z","size":22500000,"downloadUrl":"https://github.com/mihonapp/mihon/releases/download/v1.11.0/mihon-1.11.0-universal.apk","releasePage":"https://github.com/mihonapp/mihon/releases/tag/v1.11.0","stars":12500,"forks":900,"downloadCount":null,"score":55.2,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"fossifyorg-gallery","name":"Fossify Gallery","owner":"FossifyOrg","ownerType":"Organization","repo":"Gallery","repoUrl":"https://github.com/FossifyOrg/Gallery","description":"Ad-free, privacy-friendly gallery app. Browse, edit and manage your photos offline.","icon":"https://github.com/FossifyOrg.png","color":"#00897b","category":"Media","topics":["android","gallery","photos","kotlin"],"language":"Kotlin","license":"GPL-3.0","licenseDeclared":true,"version":"1.2.0","versionCode":24,"minSdk":23,"publishedAt":"2026-03-10T00:00:00Z","size":8400000,"downloadUrl":"https://github.com/FossifyOrg/Gallery/releases/download/1.2.0/Gallery-1.2.0-foss.apk","releasePage":"https://github.com/FossifyOrg/Gallery/releases/tag/1.2.0","stars":2100,"forks":180,"downloadCount":null,"score":33.1,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"brave-browser","name":"Brave","owner":"brave","ownerType":"Organization","repo":"browser-android-tabs","repoUrl":"https://github.com/brave/browser-android-tabs","description":"Privacy-focused Android browser with built-in ad blocker and HTTPS everywhere.","icon":"https://github.com/brave.png","color":"#fb542b","category":"Internet","topics":["android","browser","privacy","kotlin"],"language":"Kotlin","license":"MPL-2.0","licenseDeclared":true,"version":"1.66.115","versionCode":166115,"minSdk":24,"publishedAt":"2026-04-05T00:00:00Z","size":215000000,"downloadUrl":"https://github.com/brave/browser-android-tabs/releases/download/v1.66.115/Brave.apk","releasePage":"https://github.com/brave/browser-android-tabs/releases/tag/v1.66.115","stars":610,"forks":220,"downloadCount":null,"score":29.4,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"bitwarden-mobile","name":"Bitwarden","owner":"bitwarden","ownerType":"Organization","repo":"mobile","repoUrl":"https://github.com/bitwarden/mobile","description":"Open source password manager. Store and autofill logins securely across all your devices.","icon":"https://github.com/bitwarden.png","color":"#175ddc","category":"Security","topics":["android","password-manager","security","csharp"],"language":"C#","license":"GPL-3.0","licenseDeclared":true,"version":"2026.4.0","versionCode":50400,"minSdk":25,"publishedAt":"2026-04-22T00:00:00Z","size":78000000,"downloadUrl":"https://github.com/bitwarden/mobile/releases/download/v2026.4.0/com.x8bit.bitwarden.apk","releasePage":"https://github.com/bitwarden/mobile/releases/tag/v2026.4.0","stars":2300,"forks":1100,"downloadCount":null,"score":31.0,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"osmandapp-osmand","name":"OsmAnd","owner":"osmandapp","ownerType":"Organization","repo":"OsmAnd","repoUrl":"https://github.com/osmandapp/OsmAnd","description":"Offline/online maps and navigation for Android, built on OpenStreetMap data.","icon":"https://github.com/osmandapp.png","color":"#388e3c","category":"Tools","topics":["android","maps","navigation","openstreetmap","java"],"language":"Java","license":"GPL-3.0","licenseDeclared":true,"version":"4.8.4","versionCode":484,"minSdk":23,"publishedAt":"2026-02-09T00:00:00Z","size":145000000,"downloadUrl":"https://github.com/osmandapp/OsmAnd/releases/download/4.8.4/OsmAnd-default.apk","releasePage":"https://github.com/osmandapp/OsmAnd/releases/tag/4.8.4","stars":4900,"forks":1200,"downloadCount":null,"score":45.9,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"keepassdexandroid-keepassdx","name":"KeePassDX","owner":"Kunzisoft","ownerType":"Organization","repo":"KeePassDX","repoUrl":"https://github.com/Kunzisoft/KeePassDX","description":"Lightweight password manager for Android, compatible with KeePass databases.","icon":"https://github.com/Kunzisoft.png","color":"#1565c0","category":"Security","topics":["android","password","keepass","security","kotlin"],"language":"Kotlin","license":"GPL-3.0","licenseDeclared":true,"version":"4.0.3","versionCode":76,"minSdk":21,"publishedAt":"2026-03-25T00:00:00Z","size":12000000,"downloadUrl":"https://github.com/Kunzisoft/KeePassDX/releases/download/4.0.3/KeePassDX-4.0.3-universal.apk","releasePage":"https://github.com/Kunzisoft/KeePassDX/releases/tag/4.0.3","stars":4500,"forks":300,"downloadCount":null,"score":44.1,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"simplemobiletools-simple-calendar","name":"Simple Calendar","owner":"SimpleMobileTools","ownerType":"Organization","repo":"Simple-Calendar","repoUrl":"https://github.com/SimpleMobileTools/Simple-Calendar","description":"A simple calendar with events, reminders and widgets. No ads, no internet permission.","icon":"https://github.com/SimpleMobileTools.png","color":"#c62828","category":"Productivity","topics":["android","calendar","kotlin"],"language":"Kotlin","license":"GPL-3.0","licenseDeclared":true,"version":"6.22.5","versionCode":228,"minSdk":23,"publishedAt":"2025-12-12T00:00:00Z","size":6100000,"downloadUrl":"https://github.com/SimpleMobileTools/Simple-Calendar/releases/download/6.22.5/calendar-release.apk","releasePage":"https://github.com/SimpleMobileTools/Simple-Calendar/releases/tag/6.22.5","stars":3700,"forks":1300,"downloadCount":null,"score":36.8,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"newpipe-newpipe","name":"NewPipe","owner":"TeamNewPipe","ownerType":"Organization","repo":"NewPipe","repoUrl":"https://github.com/TeamNewPipe/NewPipe","description":"A lightweight YouTube frontend with background play and downloads. No Google services required.","icon":"https://github.com/TeamNewPipe.png","color":"#cd201f","category":"Media","topics":["android","youtube","media","java"],"language":"Java","license":"GPL-3.0","licenseDeclared":true,"version":"0.27.7","versionCode":997,"minSdk":21,"publishedAt":"2026-01-15T00:00:00Z","size":9200000,"downloadUrl":"https://github.com/TeamNewPipe/NewPipe/releases/download/v0.27.7/NewPipe_v0.27.7.apk","releasePage":"https://github.com/TeamNewPipe/NewPipe/releases/tag/v0.27.7","stars":32000,"forks":3100,"downloadCount":null,"score":58.9,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"vlc-vlc-android","name":"VLC for Android","owner":"videolan","ownerType":"Organization","repo":"vlc-android","repoUrl":"https://github.com/videolan/vlc-android","description":"Free and open source cross-platform multimedia player that plays most multimedia files.","icon":"https://github.com/videolan.png","color":"#ff8800","category":"Media","topics":["android","video","media-player","java"],"language":"Java","license":"GPL-2.0","licenseDeclared":true,"version":"3.6.5","versionCode":36050,"minSdk":21,"publishedAt":"2026-02-28T00:00:00Z","size":48000000,"downloadUrl":"https://github.com/videolan/vlc-android/releases/download/3.6.5/VLC-Android-3.6.5-arm64-v8a.apk","releasePage":"https://github.com/videolan/vlc-android/releases/tag/3.6.5","stars":2600,"forks":700,"downloadCount":null,"score":40.2,"recommendedAsset":{"arch":"arm64-v8a","abi":"arm64-v8a"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"},
  {"slug":"syncthing-android","name":"Syncthing","owner":"syncthing","ownerType":"Organization","repo":"syncthing-android","repoUrl":"https://github.com/syncthing/syncthing-android","description":"Continuous file synchronization between devices. Decentralised, peer-to-peer, no cloud.","icon":"https://github.com/syncthing.png","color":"#0891b2","category":"Tools","topics":["android","sync","file-sharing","go"],"language":"Go","license":"MPL-2.0","licenseDeclared":true,"version":"1.27.12","versionCode":4483,"minSdk":21,"publishedAt":"2025-10-30T00:00:00Z","size":28000000,"downloadUrl":"https://github.com/syncthing/syncthing-android/releases/download/1.27.12/syncthing-android-1.27.12-Universal.apk","releasePage":"https://github.com/syncthing/syncthing-android/releases/tag/1.27.12","stars":6400,"forks":1500,"downloadCount":null,"score":42.6,"recommendedAsset":{"arch":"universal","abi":"universal"},"screenshots":[],"archived":false,"indexedAt":"2026-06-14T09:00:00Z"}
]}
"""


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="APKHub indexer")
    p.add_argument("--config", default="indexer/config.toml")
    p.add_argument("--out", default="app/data", help="output directory for JSON")
    p.add_argument("--seed", action="store_true", help="write a demo dataset (offline) and exit")
    args = p.parse_args(argv)

    out_dir = Path(args.out).resolve()
    if args.seed:
        write_seed(out_dir)
        return 0

    config_path = Path(args.config)
    if not config_path.exists():
        human_log(event="config_missing", path=str(config_path))
        return 2
    with config_path.open("rb") as f:
        cfg = tomllib.load(f)

    import os

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        human_log(event="warn", msg="GITHUB_TOKEN unset; unauthenticated rate limit (60/h) applies")

    try:
        run(cfg, out_dir, token)
    except requests.HTTPError as e:
        human_log(event="fatal", error=str(e), status=getattr(e.response, "status_code", None))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
