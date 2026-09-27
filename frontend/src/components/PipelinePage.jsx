import React from "react";

export default function PipelinePage({ stats }) {
  return (
    <section>
      <div className="panel">
        <h2>Pipeline overview</h2>
        <p className="muted">
          Postings flow through a distributed pipeline: Celery workers scrape sources in
          parallel (Redis broker), postings are deduplicated and enriched with extracted
          skills, then embedded and upserted into a FAISS vector index served by the
          embedding microservice.
        </p>
        <div className="pipeline-diagram">
          <span className="node">Sources</span>
          <span className="arrow">→</span>
          <span className="node">Celery workers ×3</span>
          <span className="arrow">→</span>
          <span className="node">Postgres</span>
          <span className="arrow">→</span>
          <span className="node">Embedding service</span>
          <span className="arrow">→</span>
          <span className="node">FAISS index</span>
          <span className="arrow">→</span>
          <span className="node">Gateway API</span>
        </div>
      </div>

      {stats && (
        <div className="report-grid">
          <div className="panel">
            <h3>Corpus</h3>
            <ul className="kv-list">
              <li><span>Total jobs</span><strong>{stats.total_jobs.toLocaleString()}</strong></li>
              <li><span>Vectors indexed</span><strong>{stats.total_indexed.toLocaleString()}</strong></li>
              {Object.entries(stats.sources).map(([src, n]) => (
                <li key={src}><span>source: {src}</span><strong>{n.toLocaleString()}</strong></li>
              ))}
              <li>
                <span>Avg query latency</span>
                <strong>{stats.avg_query_latency_ms != null ? `${stats.avg_query_latency_ms} ms` : "—"}</strong>
              </li>
            </ul>
          </div>
          <div className="panel">
            <h3>Recent scrape runs</h3>
            {stats.last_runs.length === 0 && <p className="empty">No runs recorded yet.</p>}
            <table className="runs-table">
              <thead>
                <tr><th>#</th><th>source</th><th>status</th><th>found</th><th>new</th><th>worker</th></tr>
              </thead>
              <tbody>
                {stats.last_runs.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{r.source}</td>
                    <td><span className={`pill pill-${r.status}`}>{r.status}</span></td>
                    <td>{r.jobs_found}</td>
                    <td>{r.jobs_new}</td>
                    <td className="mono">{r.worker}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
