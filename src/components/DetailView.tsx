import {
  ArrowLeft,
  Star,
  Download,
  Heart,
  Clock,
  ExternalLink,
  Shield,
  Code,
  Tag,
  Cpu,
  Package,
} from "lucide-react";
import type { AppRecord } from "../data/seedData";
import { fmtSize, fmtNum, fmtDate, initials, timeAgo } from "../utils/format";

interface DetailViewProps {
  app: AppRecord;
  isFav: boolean;
  onFavToggle: () => void;
  onBack: () => void;
}

export default function DetailView({
  app,
  isFav,
  onFavToggle,
  onBack,
}: DetailViewProps) {
  return (
    <div className="detail-view">
      <button className="back-btn" onClick={onBack}>
        <ArrowLeft size={18} />
        Back to catalogue
      </button>

      <div className="detail-header">
        <div
          className="detail-icon"
          style={{ background: app.color }}
          aria-hidden="true"
        >
          {initials(app.name)}
        </div>

        <div className="detail-info">
          <h1 className="detail-name">{app.name}</h1>
          <div className="detail-owner">
            by{" "}
            <a href={app.repoUrl} target="_blank" rel="noopener">
              {app.owner}
            </a>
          </div>
          <p className="detail-desc">
            {app.description || "No description available."}
          </p>

          <div className="detail-actions">
            <a
              className="btn primary"
              href={app.downloadUrl || "#"}
              target="_blank"
              rel="noopener nofollow"
              title="Download APK from official GitHub release"
            >
              <Download size={18} />
              Download APK ({fmtSize(app.size)})
            </a>

            <button
              className={`btn outline ${isFav ? "fav-active" : ""}`}
              onClick={onFavToggle}
            >
              <Heart
                size={18}
                fill={isFav ? "currentColor" : "none"}
              />
              {isFav ? "Favourited" : "Favourite"}
            </button>

            <a
              className="btn outline"
              href={app.releasePage || app.repoUrl}
              target="_blank"
              rel="noopener"
            >
              <ExternalLink size={18} />
              Release Page
            </a>
          </div>
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-card">
          <h3>
            <Star size={16} /> Popularity
          </h3>
          <div className="stat-row">
            <div className="stat-item">
              <span className="stat-value">{fmtNum(app.stars)}</span>
              <span className="stat-label">Stars</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{fmtNum(app.forks)}</span>
              <span className="stat-label">Forks</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{app.score.toFixed(1)}</span>
              <span className="stat-label">Score</span>
            </div>
          </div>
        </div>

        <div className="detail-card">
          <h3>
            <Package size={16} /> Release Info
          </h3>
          <div className="info-list">
            <div className="info-row">
              <Tag size={14} />
              <span>Version</span>
              <strong>v{app.version || "?"}</strong>
            </div>
            <div className="info-row">
              <Clock size={14} />
              <span>Published</span>
              <strong>{fmtDate(app.publishedAt)} ({timeAgo(app.publishedAt)})</strong>
            </div>
            <div className="info-row">
              <Cpu size={14} />
              <span>Architecture</span>
              <strong>{app.recommendedAsset?.arch || "universal"}</strong>
            </div>
            <div className="info-row">
              <Download size={14} />
              <span>Size</span>
              <strong>{fmtSize(app.size)}</strong>
            </div>
          </div>
        </div>

        <div className="detail-card">
          <h3>
            <Shield size={16} /> Trust & License
          </h3>
          <div className="info-list">
            <div className="info-row">
              <Shield size={14} />
              <span>License</span>
              <strong className={app.licenseDeclared ? "green" : "amber"}>
                {app.license || "Not declared"}
              </strong>
            </div>
            <div className="info-row">
              <Code size={14} />
              <span>Language</span>
              <strong>{app.language || "—"}</strong>
            </div>
            <div className="info-row">
              <span style={{ width: 14 }}>📁</span>
              <span>Category</span>
              <strong>{app.category}</strong>
            </div>
            {app.minSdk && (
              <div className="info-row">
                <span style={{ width: 14 }}>📱</span>
                <span>Min SDK</span>
                <strong>API {app.minSdk}</strong>
              </div>
            )}
          </div>
        </div>

        {app.topics.length > 0 && (
          <div className="detail-card">
            <h3>
              <Tag size={16} /> Topics
            </h3>
            <div className="topic-chips">
              {app.topics.map((t) => (
                <span key={t} className="topic-chip">
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="detail-disclaimer">
        <Shield size={14} />
        <p>
          <strong>Official source only.</strong> This download links directly to
          the{" "}
          <a href={app.releasePage || app.repoUrl} target="_blank" rel="noopener">
            official GitHub release
          </a>
          . APKHub never re-hosts or modifies binaries. Download at your own
          discretion.
        </p>
      </div>
    </div>
  );
}
