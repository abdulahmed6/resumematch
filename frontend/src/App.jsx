import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import SearchPage from "./components/SearchPage.jsx";
import SkillGapPage from "./components/SkillGapPage.jsx";
import PipelinePage from "./components/PipelinePage.jsx";

const TABS = [
  { id: "search", label: "Semantic Search" },
  { id: "skillgap", label: "Skill-Gap Analysis" },
  { id: "pipeline", label: "Pipeline" },
];

export default function App() {
  const [tab, setTab] = useState("search");
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats(null));
  }, [tab]);

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-mark">RM</span>
            <div>
              <h1>ResumeMatch</h1>
              <p className="tagline">Distributed job-matching pipeline with semantic search</p>
            </div>
          </div>
          {stats && (
            <div className="header-stats">
              <div className="stat">
                <span className="stat-value">{stats.total_jobs.toLocaleString()}</span>
                <span className="stat-label">jobs scraped</span>
              </div>
              <div className="stat">
                <span className="stat-value">{stats.total_indexed.toLocaleString()}</span>
                <span className="stat-label">vectors indexed</span>
              </div>
              <div className="stat">
                <span className="stat-value">
                  {stats.avg_query_latency_ms != null ? `${stats.avg_query_latency_ms} ms` : "—"}
                </span>
                <span className="stat-label">avg query latency</span>
              </div>
            </div>
          )}
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="main">
        {tab === "search" && <SearchPage />}
        {tab === "skillgap" && <SkillGapPage />}
        {tab === "pipeline" && <PipelinePage stats={stats} />}
      </main>

      <footer className="footer">
        FastAPI · Celery · Redis · FAISS · Postgres · React — ResumeMatch demo
      </footer>
    </div>
  );
}
