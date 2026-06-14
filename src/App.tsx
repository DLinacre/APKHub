import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { SEED_APPS } from "./data/seedData";
import type { AppRecord } from "./data/seedData";
import { SearchIndex } from "./utils/searchIndex";
import { useTheme } from "./hooks/useTheme";
import { useFavourites } from "./hooks/useFavourites";
import TopBar from "./components/TopBar";
import FilterBar from "./components/FilterBar";
import AppCard from "./components/AppCard";
import DetailView from "./components/DetailView";
import Hero from "./components/Hero";

type View = "home" | "favourites" | "detail";

function sortApps(apps: AppRecord[], key: string): AppRecord[] {
  const sorted = [...apps];
  switch (key) {
    case "trending":
      return sorted.sort((a, b) => b.score - a.score);
    case "stars":
      return sorted.sort((a, b) => b.stars - a.stars);
    case "newest":
      return sorted.sort(
        (a, b) =>
          new Date(b.publishedAt || 0).getTime() -
          new Date(a.publishedAt || 0).getTime()
      );
    case "name":
      return sorted.sort((a, b) => a.name.localeCompare(b.name));
    case "size":
      return sorted.sort((a, b) => (b.size || 0) - (a.size || 0));
    default:
      return sorted;
  }
}

export default function App() {
  const { theme, toggle: toggleTheme } = useTheme();
  const { toggle: toggleFav, isFav, count: favCount } = useFavourites();
  const apps = SEED_APPS;

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [sort, setSort] = useState("trending");
  const [language, setLanguage] = useState("");
  const [license, setLicense] = useState("");
  const [view, setView] = useState<View>("home");
  const [detailSlug, setDetailSlug] = useState<string | null>(null);

  const searchIndex = useRef(new SearchIndex());

  // Build search index
  useEffect(() => {
    searchIndex.current.build(apps);
  }, [apps]);

  // Handle hash routing
  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash;
      if (hash.startsWith("#/app/")) {
        const slug = hash.slice(6);
        setDetailSlug(slug);
        setView("detail");
      } else if (hash === "#/favourites") {
        setView("favourites");
        setDetailSlug(null);
      } else {
        setView("home");
        setDetailSlug(null);
      }
    };
    handleHash();
    window.addEventListener("hashchange", handleHash);
    return () => window.removeEventListener("hashchange", handleHash);
  }, []);

  // Keyboard shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        document.getElementById("search")?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const navigateTo = useCallback((v: View, slug?: string) => {
    if (v === "detail" && slug) {
      window.location.hash = `#/app/${slug}`;
    } else if (v === "favourites") {
      window.location.hash = "#/favourites";
    } else {
      window.location.hash = "";
    }
  }, []);

  // Derive filtered + sorted apps
  const filteredApps = useMemo(() => {
    let indices: number[];

    if (query.trim()) {
      indices = searchIndex.current.search(query, apps);
    } else {
      indices = apps.map((_, i) => i);
    }

    let result = indices.map((i) => apps[i]);

    // Category filter
    if (category !== "All") {
      result = result.filter((a) => a.category === category);
    }

    // Language filter
    if (language) {
      result = result.filter((a) => a.language === language);
    }

    // License filter
    if (license) {
      result = result.filter((a) => a.license === license);
    }

    // Favourites view
    if (view === "favourites") {
      result = result.filter((a) => isFav(a.slug));
    }

    // Sort (unless search is active, which has its own ranking)
    if (!query.trim()) {
      result = sortApps(result, sort);
    }

    return result;
  }, [apps, query, category, sort, language, license, view, isFav]);

  // Trending apps (top 6 by score)
  const trendingApps = useMemo(
    () => [...apps].sort((a, b) => b.score - a.score).slice(0, 6),
    [apps]
  );

  // Detail app
  const detailApp = useMemo(
    () => apps.find((a) => a.slug === detailSlug) || null,
    [apps, detailSlug]
  );

  const isShowingFavs = view === "favourites";

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <TopBar
        query={query}
        onQueryChange={setQuery}
        theme={theme}
        onThemeToggle={toggleTheme}
        favCount={favCount}
        onFavClick={() => navigateTo(isShowingFavs ? "home" : "favourites")}
        showingFavs={isShowingFavs}
        onLogoClick={() => {
          setQuery("");
          setCategory("All");
          setSort("trending");
          setLanguage("");
          setLicense("");
          navigateTo("home");
        }}
      />

      {view !== "detail" && (
        <FilterBar
          apps={apps}
          category={category}
          onCategoryChange={setCategory}
          sort={sort}
          onSortChange={setSort}
          language={language}
          onLanguageChange={setLanguage}
          license={license}
          onLicenseChange={setLicense}
        />
      )}

      <main id="main">
        <div id="view">
          {view === "detail" && detailApp ? (
            <DetailView
              app={detailApp}
              isFav={isFav(detailApp.slug)}
              onFavToggle={() => toggleFav(detailApp.slug)}
              onBack={() => navigateTo("home")}
            />
          ) : (
            <>
              {view === "home" && !query && category === "All" && (
                <>
                  <Hero appCount={apps.length} />

                  <div className="section-title">
                    🔥 Trending
                  </div>
                  <div className="trending">
                    {trendingApps.map((app) => (
                      <AppCard
                        key={app.slug}
                        app={app}
                        isFav={isFav(app.slug)}
                        onFavToggle={() => toggleFav(app.slug)}
                        onClick={() => navigateTo("detail", app.slug)}
                      />
                    ))}
                  </div>

                  <div className="section-title" style={{ marginTop: 32 }}>
                    📱 All Apps
                  </div>
                </>
              )}

              {view === "favourites" && (
                <div className="view-head">
                  <h1>❤️ Favourites</h1>
                  <span className="count">
                    {filteredApps.length} app
                    {filteredApps.length !== 1 ? "s" : ""}
                  </span>
                </div>
              )}

              {query && (
                <div className="view-head">
                  <h1>
                    Search: &ldquo;{query}&rdquo;
                  </h1>
                  <span className="count">
                    {filteredApps.length} result
                    {filteredApps.length !== 1 ? "s" : ""}
                  </span>
                  <button
                    className="btn outline clear"
                    onClick={() => setQuery("")}
                  >
                    Clear
                  </button>
                </div>
              )}

              {filteredApps.length > 0 ? (
                <div className="grid">
                  {filteredApps.map((app) => (
                    <AppCard
                      key={app.slug}
                      app={app}
                      isFav={isFav(app.slug)}
                      onFavToggle={() => toggleFav(app.slug)}
                      onClick={() => navigateTo("detail", app.slug)}
                    />
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">📭</div>
                  <h3>No apps found</h3>
                  <p>
                    {view === "favourites"
                      ? "You haven't favourited any apps yet. Browse the catalogue and tap the ❤️ to save apps here."
                      : "Try adjusting your search or filters."}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <p>
            <strong>APKHub</strong> — An open-source catalogue of Android apps
            from GitHub.
          </p>
          <p className="footer-meta">
            Metadata only. Every download links to the official GitHub release
            asset.
            <br />
            {apps.length} apps indexed •{" "}
            <a
              href="https://github.com/LIN4CRE/GitDroid"
              target="_blank"
              rel="noopener"
            >
              Source on GitHub
            </a>
          </p>
        </div>
      </footer>
    </>
  );
}
