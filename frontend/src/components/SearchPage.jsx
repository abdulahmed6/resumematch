import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import JobCard from "./JobCard.jsx";

const EXAMPLES = [
  "senior python engineer with fastapi and postgres",
  "machine learning engineer llms pytorch",
  "remote devops kubernetes terraform",
  "data engineer spark airflow kafka",
];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [seniority, setSeniority] = useState("");
  const [topK, setTopK] = useState(10);
  const [resp, setResp] = useState(null);
  const [recent, setRecent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.jobs(6).then(setRecent).catch(() => setRecent([]));
  }, []);

  const runSearch = async (q) => {
    const text = (q ?? query).trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.search(text, topK, remoteOnly, seniority || null);
      setResp(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section>
      <div className="panel">
        <form
          className="search-bar"
          onSubmit={(e) => {
            e.preventDefault();
            runSearch();
          }}
        >
          <input
            type="text"
            value={query}
            placeholder="Describe your ideal role — e.g. 'backend engineer, python, distributed systems'"
            onChange={(e) => setQuery(e.target.value)}
            aria-label="search query"
          />
          <button type="submit" className="btn primary" disabled={loading}>
            {loading ? "Searching…" : "Search"}
          </button>
        </form>
        <div className="filters">
          <label className="checkbox">
            <input type="checkbox" checked={remoteOnly} onChange={(e) => setRemoteOnly(e.target.checked)} />
            Remote only
          </label>
          <select value={seniority} onChange={(e) => setSeniority(e.target.value)} aria-label="seniority">
            <option value="">Any seniority</option>
            <option value="junior">Junior</option>
            <option value="mid">Mid</option>
            <option value="senior">Senior</option>
            <option value="staff">Staff</option>
          </select>
          <select value={topK} onChange={(e) => setTopK(Number(e.target.value))} aria-label="results count">
            <option value={5}>Top 5</option>
            <option value={10}>Top 10</option>
            <option value={25}>Top 25</option>
          </select>
        </div>
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              className="chip chip-btn"
              onClick={() => {
                setQuery(ex);
                runSearch(ex);
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      {resp && (
        <>
          <p className="result-meta">
            {resp.results.length} results from {resp.total_indexed.toLocaleString()} indexed postings ·{" "}
            <strong>{resp.latency_ms} ms</strong> query latency
          </p>
          <div className="job-list">
            {resp.results.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
            {resp.results.length === 0 && <p className="empty">No results — try a broader query.</p>}
          </div>
        </>
      )}

      {!resp && recent && recent.length > 0 && (
        <>
          <p className="result-meta">Recently scraped postings</p>
          <div className="job-list">
            {recent.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
