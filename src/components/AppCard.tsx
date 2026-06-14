import { Heart, Star, Clock, Download } from "lucide-react";
import type { AppRecord } from "../data/seedData";
import { fmtSize, fmtNum, fmtDate, initials } from "../utils/format";

interface AppCardProps {
  app: AppRecord;
  isFav: boolean;
  onFavToggle: () => void;
  onClick: () => void;
}

export default function AppCard({ app, isFav, onFavToggle, onClick }: AppCardProps) {
  return (
    <article className="card" onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') onClick(); }}>
      <div className="card-top">
        <div
          className="app-icon placeholder"
          style={{ background: app.color }}
          aria-hidden="true"
        >
          {initials(app.name)}
        </div>
        <div className="card-titles">
          <div className="card-name">{app.name}</div>
          <div className="card-owner">
            by{" "}
            <a
              href={app.repoUrl}
              target="_blank"
              rel="noopener"
              onClick={(e) => e.stopPropagation()}
            >
              {app.owner}
            </a>
          </div>
        </div>
        <button
          className={`fav-toggle ${isFav ? "on" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            onFavToggle();
          }}
          title={isFav ? "Remove from favourites" : "Add to favourites"}
          aria-label="Toggle favourite"
          aria-pressed={isFav}
        >
          <Heart size={20} fill={isFav ? "currentColor" : "none"} />
        </button>
      </div>

      <p className="card-desc">
        {app.description || "No description available."}
      </p>

      <div className="card-meta">
        <span className="meta">v{app.version || "?"}</span>
        {app.license ? (
          <span className="meta license" title="License">
            {app.license}
          </span>
        ) : (
          <span className="meta warn" title="License not declared">
            No license
          </span>
        )}
        {app.language && <span className="meta">{app.language}</span>}
        {app.recommendedAsset?.arch && (
          <span className="meta">{app.recommendedAsset.arch}</span>
        )}
      </div>

      <div className="card-foot">
        <div className="card-stats">
          <span className="stat">
            <Star size={13} />
            {fmtNum(app.stars)}
          </span>
          <span className="stat">{fmtSize(app.size)}</span>
          <span className="stat" title={fmtDate(app.publishedAt)}>
            <Clock size={13} />
            {fmtDate(app.publishedAt)}
          </span>
        </div>
        <a
          className="btn"
          href={app.downloadUrl || "#"}
          target="_blank"
          rel="noopener nofollow"
          onClick={(e) => e.stopPropagation()}
          title="Download APK from GitHub"
        >
          <Download size={15} />
          Get
        </a>
      </div>
    </article>
  );
}
