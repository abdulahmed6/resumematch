const BASE = "";

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json();
}

export const api = {
  search: (query, topK = 10, remoteOnly = false, seniority = null) =>
    request("/api/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        top_k: topK,
        remote_only: remoteOnly,
        seniority: seniority || null,
      }),
    }),
  jobs: (limit = 20, offset = 0) => request(`/api/jobs?limit=${limit}&offset=${offset}`),
  job: (id) => request(`/api/jobs/${id}`),
  skillGap: (resumeText, query = null, topK = 20) =>
    request("/api/skill-gap", {
      method: "POST",
      body: JSON.stringify({ resume_text: resumeText, query, top_k: topK }),
    }),
  uploadResume: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/resume/upload", { method: "POST", body: form });
  },
  stats: () => request("/api/stats"),
  skills: () => request("/api/skills"),
};
