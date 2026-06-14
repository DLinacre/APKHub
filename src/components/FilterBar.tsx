import { CATEGORIES } from "../data/seedData";
import type { AppRecord } from "../data/seedData";

interface FilterBarProps {
  apps: AppRecord[];
  category: string;
  onCategoryChange: (c: string) => void;
  sort: string;
  onSortChange: (s: string) => void;
  language: string;
  onLanguageChange: (l: string) => void;
  license: string;
  onLicenseChange: (l: string) => void;
}

export default function FilterBar({
  apps,
  category,
  onCategoryChange,
  sort,
  onSortChange,
  language,
  onLanguageChange,
  license,
  onLicenseChange,
}: FilterBarProps) {
  const languages = [
    ...new Set(apps.map((a) => a.language).filter(Boolean) as string[]),
  ].sort();
  const licenses = [
    ...new Set(apps.map((a) => a.license).filter(Boolean) as string[]),
  ].sort();

  return (
    <div className="filters">
      <div className="chips" role="tablist" aria-label="Category filter">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            className={`chip ${category === cat ? "active" : ""}`}
            onClick={() => onCategoryChange(cat)}
            role="tab"
            aria-selected={category === cat}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="filter-selects">
        <div className="select">
          <span>Sort</span>
          <select value={sort} onChange={(e) => onSortChange(e.target.value)}>
            <option value="trending">🔥 Trending</option>
            <option value="stars">⭐ Stars</option>
            <option value="newest">🕐 Newest</option>
            <option value="name">🔤 Name</option>
            <option value="size">📦 Size</option>
          </select>
        </div>

        <div className="select">
          <span>Language</span>
          <select
            value={language}
            onChange={(e) => onLanguageChange(e.target.value)}
          >
            <option value="">All</option>
            {languages.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>

        <div className="select">
          <span>License</span>
          <select
            value={license}
            onChange={(e) => onLicenseChange(e.target.value)}
          >
            <option value="">All</option>
            {licenses.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
