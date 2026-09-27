import React, { useState } from "react";

function salaryFmt(min, max) {
  if (!min && !max) return null;
  const f = (v) => `$${Math.round(v / 1000)}k`;
  return `${min ? f(min) : "?"} – ${max ? f(max) : "?"}`;
}

export default function JobCard({ job, highlightSkills = [] }) {
  const [expanded, setExpanded] = useState(false);
  const salary = salaryFmt(job.salary_min, job.salary_max);
  const hl = new Set(highlightSkills);

  return (
    <article className="job-card">
      <div className="job-head">
        <div>
          <h3>{job.title}</h3>
          <p className="job-meta">
            <strong>{job.company}</strong> · {job.location}
            {job.remote && <span className="pill pill-remote">remote</span>}
            <span className={`pill pill-${job.seniority}`}>{job.seniority}</span>
          </p>
        </div>
        <div className="job-side">
          {job.score != null && (
            <span className="score" title="cosine similarity">
              {(job.score * 100).toFixed(1)}% match
            </span>
          )}
          {salary && <span className="salary">{salary}</span>}
        </div>
      </div>
      <div className="skill-row">
        {(job.skills || []).map((s) => (
          <span key={s} className={`chip ${hl.size ? (hl.has(s) ? "chip-have" : "chip-missing") : ""}`}>
            {s}
          </span>
        ))}
      </div>
      <p className={`job-desc ${expanded ? "expanded" : ""}`}>{job.description}</p>
      <button className="link-btn" onClick={() => setExpanded(!expanded)}>
        {expanded ? "Show less" : "Show full description"}
      </button>
    </article>
  );
}
