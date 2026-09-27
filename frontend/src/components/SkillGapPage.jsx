import React, { useRef, useState } from "react";
import { api } from "../api.js";
import JobCard from "./JobCard.jsx";

const SAMPLE_RESUME = `Abdul Ahmed — Software Engineer

Experience building backend services with Python, FastAPI and PostgreSQL.
Comfortable with Docker, Git, REST APIs and unit testing with pytest.
Built data pipelines with pandas and SQL; some exposure to AWS (EC2, S3).
Frontend work in JavaScript and React on side projects.`;

export default function SkillGapPage() {
  const [resumeText, setResumeText] = useState("");
  const [targetQuery, setTargetQuery] = useState("");
  const [report, setReport] = useState(null);
  const [jobsById, setJobsById] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  const analyze = async () => {
    if (!resumeText.trim()) {
      setError("Paste or upload your resume first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await api.skillGap(resumeText, targetQuery.trim() || null, 20);
      setReport(r);
      const top = r.per_job.slice(0, 5);
      const jobs = await Promise.all(top.map((p) => api.job(p.job_id).catch(() => null)));
      const map = {};
      jobs.forEach((j) => j && (map[j.id] = j));
      setJobsById(map);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const onUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    try {
      const r = await api.uploadResume(file);
      setResumeText(r.text);
    } catch (err) {
      setError(err.message);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <section>
      <div className="panel">
        <div className="panel-title-row">
          <h2>Skill-gap analysis</h2>
          <div className="row-actions">
            <button className="btn ghost" onClick={() => setResumeText(SAMPLE_RESUME)}>
              Use sample resume
            </button>
            <label className="btn ghost">
              Upload .txt
              <input ref={fileRef} type="file" accept=".txt,.md,text/plain" onChange={onUpload} hidden />
            </label>
          </div>
        </div>
        <textarea
          rows={8}
          value={resumeText}
          onChange={(e) => setResumeText(e.target.value)}
          placeholder="Paste your resume text here…"
          aria-label="resume text"
        />
        <div className="search-bar">
          <input
            type="text"
            value={targetQuery}
            onChange={(e) => setTargetQuery(e.target.value)}
            placeholder="Optional target role — e.g. 'senior ML engineer' (defaults to resume similarity)"
            aria-label="target role"
          />
          <button className="btn primary" onClick={analyze} disabled={loading}>
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      {report && (
        <div className="report">
          <div className="report-grid">
            <div className="panel metric-panel">
              <span className="metric-big">{Math.round(report.coverage * 100)}%</span>
              <span className="stat-label">avg skill coverage across {report.matched_jobs} matched jobs</span>
            </div>
            <div className="panel">
              <h3>Skills detected in your resume ({report.resume_skills.length})</h3>
              <div className="skill-row">
                {report.resume_skills.map((s) => (
                  <span key={s} className="chip chip-have">{s}</span>
                ))}
                {report.resume_skills.length === 0 && <p className="empty">No taxonomy skills detected.</p>}
              </div>
            </div>
          </div>

          <div className="report-grid">
            <div className="panel">
              <h3>Top missing skills</h3>
              {report.missing_skills.length === 0 && <p className="empty">No gaps found 🎉</p>}
              <ul className="bar-list">
                {report.missing_skills.slice(0, 12).map((m) => (
                  <li key={m.skill}>
                    <span className="bar-label">{m.skill}</span>
                    <span className="bar-track">
                      <span className="bar-fill missing" style={{ width: `${m.share * 100}%` }} />
                    </span>
                    <span className="bar-value">{Math.round(m.share * 100)}% of jobs</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="panel">
              <h3>Your strongest matched skills</h3>
              <ul className="bar-list">
                {report.matched_skills.slice(0, 12).map((m) => (
                  <li key={m.skill}>
                    <span className="bar-label">{m.skill}</span>
                    <span className="bar-track">
                      <span className="bar-fill have" style={{ width: `${m.share * 100}%` }} />
                    </span>
                    <span className="bar-value">{Math.round(m.share * 100)}% of jobs</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <h3 className="section-title">Best-fit postings</h3>
          <div className="job-list">
            {report.per_job.slice(0, 5).map((p) =>
              jobsById[p.job_id] ? (
                <JobCard key={p.job_id} job={jobsById[p.job_id]} highlightSkills={report.resume_skills} />
              ) : (
                <div key={p.job_id} className="panel">
                  <strong>{p.title}</strong> at {p.company} — coverage{" "}
                  {p.coverage != null ? `${Math.round(p.coverage * 100)}%` : "n/a"}
                </div>
              )
            )}
          </div>
        </div>
      )}
    </section>
  );
}
