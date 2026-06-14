import { Search, Sun, Moon, Heart } from "lucide-react";

interface TopBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  theme: "dark" | "light";
  onThemeToggle: () => void;
  favCount: number;
  onFavClick: () => void;
  showingFavs: boolean;
  onLogoClick: () => void;
}

export default function TopBar({
  query,
  onQueryChange,
  theme,
  onThemeToggle,
  favCount,
  onFavClick,
  showingFavs,
  onLogoClick,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <a
          href="#"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            onLogoClick();
          }}
        >
          <span className="brand-mark">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="1" width="18" height="22" rx="3" stroke="currentColor" strokeWidth="2" />
              <circle cx="12" cy="18" r="1.5" fill="currentColor" />
              <path d="M8 6h8M8 9h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </span>
          <span>
            APK<span className="brand-accent">Hub</span>
          </span>
        </a>

        <div className="search-wrap">
          <Search className="search-icon" size={18} />
          <input
            id="search"
            type="search"
            placeholder="Search apps, categories, topics…"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="search-kbd">⌘K</kbd>
        </div>

        <div className="topbar-actions">
          <button
            className={`icon-btn ${showingFavs ? "active" : ""}`}
            onClick={onFavClick}
            title="Favourites"
            aria-label="Favourites"
          >
            <Heart size={20} fill={showingFavs ? "currentColor" : "none"} />
            {favCount > 0 && <span className="badge">{favCount}</span>}
          </button>

          <button
            className="icon-btn"
            onClick={onThemeToggle}
            title="Toggle theme"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>

          <a
            href="https://github.com/LIN4CRE/GitDroid"
            target="_blank"
            rel="noopener"
            className="icon-btn"
            title="View on GitHub"
            aria-label="GitHub"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12Z"/></svg>
          </a>
        </div>
      </div>
    </header>
  );
}
