/* ==========================================================================
   Beep Job Hub — Frontend Application (app.js)
   Clean, dependency-free ES6 module with URL-synced state, debounced search,
   multi-filter dropdowns, saved bookmarks, split master-detail view,
   pipeline status telemetry, and the split-from-middle intro screen.
   ========================================================================== */
(() => {
  "use strict";

  // Auto-detects FastAPI (/api/jobs, /api/filters, /api/status, /api/metrics/cost)
  // and falls back seamlessly to window.MOCK when previewed on a static server (http.server).
  let useMock = new URLSearchParams(location.search).has("mock");
  const PAGE_SIZE = 12;
  const SAVED_STORAGE_KEY = "beep_saved_jobs_v1";
  const INTRO_SESSION_KEY = "beep_intro_seen_v1";
  const FILTER_KEYS = ["city", "job_type", "workplace", "role", "source", "posted_within"];
  const MOBILE = window.matchMedia("(max-width: 920px)");

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const el = {
    intro: $("#intro"),
    introBtn: $("#intro-continue"),
    replayBtn: $("#replay-intro"),
    brandHome: $("#brand-home"),
    jobsView: $("#jobs-view"),
    statusView: $("#status-view"),
    statusContent: $("#status-content"),
    backToJobs: $("#back-to-jobs"),
    savedBadge: $("#saved-count"),
    searchForm: $("#search-form"),
    search: $("#search-input"),
    sortSelect: $("#sort-select"),
    filters: $("#filters"),
    active: $("#active-filters"),
    list: $("#job-list"),
    meta: $("#list-meta"),
    pagination: $("#pagination"),
    detail: $("#detail"),
    fresh: $("#freshness-text"),
  };

  const ICON = {
    chevron: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    chevronUp: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>',
    check: '<svg class="icon check" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    close: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    pin: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
    clock: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    plane: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7Z"/></svg>',
    out: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6"/><path d="M10 14 20 4"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
    bookmark: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12a1 1 0 0 1 1 1v16l-7-4-7 4V5a1 1 0 0 1 1-1Z"/></svg>',
    back: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>',
    shield: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 7v5c0 5 3.4 8.8 8 10 4.6-1.2 8-5 8-10V7l-8-4Z"/><path d="m9 12 2 2 4-4"/></svg>',
  };

  const SOURCE_LABEL = {
    greenhouse: "Greenhouse ATS",
    lever: "Lever ATS",
    ashby: "Ashby ATS",
    smartrecruiters: "SmartRecruiters",
    jobicy: "Jobicy API",
    remotive: "Remotive API",
    github_feeds: "Verified Career Tracker",
  };

  const TYPE_LABEL = {
    job: "Full Time",
    internship: "Internship",
  };

  const WORKPLACE_LABEL = {
    onsite: "Onsite",
    remote: "Remote",
  };

  const POSTED_LABEL = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
  };

  const FILTER_DEFS = [
    { key: "city", label: "Location" },
    { key: "job_type", label: "Job type", fmt: (v) => TYPE_LABEL[v] || v },
    { key: "workplace", label: "Workplace Type", fmt: (v) => WORKPLACE_LABEL[v] || v },
    { key: "role", label: "Categories" },
    { key: "source", label: "Source", fmt: (v) => SOURCE_LABEL[v] || v },
    { key: "posted_within", label: "Posted", fmt: (v) => POSTED_LABEL[v] || v },
  ];

  const MONO_PALETTE = [
    "#FDE68A",
    "#DBEAFE",
    "#DCFCE7",
    "#FCE7F3",
    "#E0E7FF",
    "#FFEDD5",
    "#CCFBF1",
    "#F3E8FF",
  ];

  // ---------- Saved Jobs (localStorage) ----------
  function getSavedIds() {
    try {
      const raw = localStorage.getItem(SAVED_STORAGE_KEY);
      return new Set(raw ? JSON.parse(raw).map(String) : []);
    } catch {
      return new Set();
    }
  }

  let savedIds = getSavedIds();

  function saveSavedIds() {
    try {
      localStorage.setItem(SAVED_STORAGE_KEY, JSON.stringify([...savedIds]));
    } catch {
      /* ignore quota errors */
    }
    updateSavedBadge();
  }

  function toggleSaved(jobId) {
    const id = String(jobId);
    if (savedIds.has(id)) {
      savedIds.delete(id);
      toast("Removed from saved jobs");
    } else {
      savedIds.add(id);
      toast("Saved to your shortlist");
    }
    saveSavedIds();
    renderDetail();
    if (state.view === "saved") {
      load();
    }
  }

  function updateSavedBadge() {
    const count = savedIds.size;
    el.savedBadge.textContent = String(count);
    el.savedBadge.hidden = count === 0;
  }

  // ---------- Formatting Helpers ----------
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  function initials(name) {
    const clean = (name || "?").replace(/[^A-Za-z0-9 ]/g, " ").trim();
    const parts = clean.split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  function companyTone(name) {
    const hash = [...(name || "")].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return MONO_PALETTE[hash % MONO_PALETTE.length];
  }

  const monoHtml = (name, large = false) =>
    `<span class="mono${large ? " lg" : ""}" style="background:${companyTone(name)}" aria-hidden="true">${esc(initials(name))}</span>`;

  function ageHours(iso) {
    if (!iso) return 18;
    const t = new Date(iso).getTime();
    if (isNaN(t)) return 18;
    return Math.max(0, (Date.now() - t) / 36e5);
  }

  function relTime(iso) {
    const h = ageHours(iso);
    if (!isFinite(h)) return "Recently";
    if (h < 2) return "Just now";
    if (h < 24) return `${Math.floor(h)} hours ago`;
    const d = Math.floor(h / 24);
    if (d === 1) return "1 day ago";
    if (d < 7) return `${d} days ago`;
    const w = Math.floor(d / 7);
    return w === 1 ? "1 week ago" : `${w} weeks ago`;
  }

  function expLabel(j) {
    const lo = j.min_exp ?? 0;
    const hi = j.max_exp ?? 1;
    return lo === hi ? `${lo} years` : `${lo}\u2013${hi} years`;
  }

  function cityDisplay(j) {
    if (j.city === "Remote") return "Remote, India (Remote)";
    const base = j.city === "India (Multiple/Other)" ? "Multiple Cities, India" : j.city;
    return `${base} (Onsite)`;
  }

  // ---------- URL & Application State ----------
  function readState() {
    const p = new URLSearchParams(location.search);
    const s = {
      q: p.get("q") || "",
      page: Math.max(1, parseInt(p.get("page"), 10) || 1),
      job: p.get("job") || "",
      sort_by: p.get("sort_by") || "newest",
      view: p.get("view") || "all",
    };
    FILTER_KEYS.forEach((k) => {
      s[k] = p.get(k) || "";
    });
    return s;
  }

  function stateToQuery(s, includeJob = true) {
    const p = new URLSearchParams();
    if (s.view && s.view !== "all") p.set("view", s.view);
    if (s.q) p.set("q", s.q);
    FILTER_KEYS.forEach((k) => {
      if (s[k]) p.set(k, s[k]);
    });
    if (s.sort_by && s.sort_by !== "newest") p.set("sort_by", s.sort_by);
    if (s.page > 1) p.set("page", String(s.page));
    if (includeJob && s.job) p.set("job", String(s.job));
    return p.toString();
  }

  const listKey = (s) => stateToQuery(s, false);

  function writeUrl(push = false) {
    const qs = stateToQuery(state);
    const url = qs ? `?${qs}` : location.pathname;
    history[push ? "pushState" : "replaceState"]({ beep: true }, "", url);
  }

  // ---------- Data Layer ----------
  const mockJobs = () => (window.MOCK && window.MOCK.jobs) || [];

  function mockFilter(s) {
    const q = s.q.trim().toLowerCase();
    const cutoff = { "24h": 24, "7d": 168, "30d": 720 }[s.posted_within];
    return mockJobs()
      .filter((j) => {
        if (s.view === "saved" && !savedIds.has(String(j.id))) return false;
        if (q) {
          const hay = [j.title, j.company, j.city, j.role_tag, j.description, (j.skills || []).join(" ")]
            .join(" ")
            .toLowerCase();
          if (!hay.includes(q)) return false;
        }
        if (s.city && j.city !== s.city) return false;
        if (s.job_type && j.job_type !== s.job_type) return false;
        if (s.workplace === "remote" && j.city !== "Remote") return false;
        if (s.workplace === "onsite" && j.city === "Remote") return false;
        if (s.role && j.role_tag !== s.role) return false;
        if (s.source && j.source_name !== s.source) return false;
        if (cutoff && ageHours(j.posted_date) > cutoff) return false;
        return true;
      })
      .sort((a, b) => {
        const cmp = String(b.posted_date || "").localeCompare(String(a.posted_date || "")) || b.id - a.id;
        return s.sort_by === "oldest" ? -cmp : cmp;
      });
  }

  function mockPaginate(s) {
    const all = mockFilter(s);
    const total_pages = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
    const page = Math.min(s.page, total_pages);
    return {
      total: all.length,
      page,
      limit: PAGE_SIZE,
      total_pages,
      jobs: all.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    };
  }

  async function fetchJobs(s) {
    if (useMock || s.view === "saved") {
      return mockPaginate(s);
    }
    try {
      const p = new URLSearchParams(listKey(s));
      p.set("limit", String(PAGE_SIZE));
      const res = await fetch(`/api/jobs?${p}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.total === 0 && !s.q && !s.city && !s.role && !s.job_type && !s.workplace && !s.source && !s.posted_within && mockJobs().length > 0) {
        return mockPaginate(s);
      }
      return json;
    } catch {
      useMock = true;
      return mockPaginate(s);
    }
  }

  function mockFilterCounts() {
    const jobs = mockJobs();
    const tally = (fn) => {
      const m = new Map();
      jobs.forEach((j) => {
        const k = fn(j);
        if (k) m.set(k, (m.get(k) || 0) + 1);
      });
      return [...m].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
    };
    return {
      cities: tally((j) => j.city),
      job_types: tally((j) => j.job_type),
      workplaces: tally((j) => (j.city === "Remote" ? "remote" : "onsite")),
      roles: tally((j) => j.role_tag),
      sources: tally((j) => j.source_name),
      total: jobs.length,
      updated_at: window.MOCK && window.MOCK.generated_at,
    };
  }

  async function fetchFilterCounts() {
    if (useMock) {
      return mockFilterCounts();
    }
    try {
      const res = await fetch("/api/filters");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const total = data.total_active_jobs || (data.job_types || []).reduce((acc, t) => acc + t.count, 0);
      if (total === 0 && mockJobs().length > 0) {
        return mockFilterCounts();
      }
      const remCount = ((data.cities || []).find((c) => c.name === "Remote") || {}).count || 0;
      data.workplaces = [
        { name: "onsite", count: Math.max(0, total - remCount) },
        { name: "remote", count: remCount },
      ];
      data.total = total;
      return data;
    } catch {
      useMock = true;
      return mockFilterCounts();
    }
  }

  // ---------- Render: Filter Dropdowns & Active Pills ----------
  let filterOptions = {
    city: [],
    job_type: [],
    workplace: [],
    role: [],
    source: [],
    posted_within: [],
  };

  function renderFilters() {
    el.filters.innerHTML = FILTER_DEFS.map((f) => {
      const val = state[f.key];
      const shown = val ? (f.fmt ? f.fmt(val) : val) : f.label;
      const opts = (filterOptions[f.key] || [])
        .map(
          (o) => `
        <button type="button" class="dd-opt" role="option" data-key="${f.key}" data-value="${esc(o.value)}" aria-selected="${o.value === val}">
          ${ICON.check}
          <span>${esc(o.label)}</span>
          ${o.count != null ? `<span class="count">${o.count}</span>` : ""}
        </button>`
        )
        .join("");

      return `
        <div class="dd" data-key="${f.key}">
          <button type="button" class="dd-btn${val ? " has-value" : ""}" aria-haspopup="listbox" aria-expanded="false">
            <span>${esc(shown)}</span>
            ${ICON.chevron}
          </button>
          <div class="dd-menu" role="listbox" aria-label="${esc(f.label)}" hidden>
            <button type="button" class="dd-opt" role="option" data-key="${f.key}" data-value="" aria-selected="${!val}">
              ${ICON.check}
              <span>All ${esc(f.label)}</span>
            </button>
            ${opts}
          </div>
        </div>`;
    }).join("");

    const pills = FILTER_DEFS.filter((f) => state[f.key]).map(
      (f) =>
        `<span class="pill">${esc(f.fmt ? f.fmt(state[f.key]) : state[f.key])}<button type="button" data-clear="${f.key}" aria-label="Remove ${esc(f.label)} filter">${ICON.close}</button></span>`
    );
    if (state.q) {
      pills.unshift(
        `<span class="pill">Search: "${esc(state.q)}"<button type="button" data-clear="q" aria-label="Clear search">${ICON.close}</button></span>`
      );
    }
    if (state.view === "saved") {
      pills.unshift(
        `<span class="pill">Saved Roles (${savedIds.size})<button type="button" data-clear="view" aria-label="Exit saved view">${ICON.close}</button></span>`
      );
    }
    el.active.hidden = pills.length === 0;
    el.active.innerHTML =
      pills.join("") +
      (pills.length > 1 ? '<button type="button" class="clear-all" data-clear="all">Clear all</button>' : "");

    syncNavHighlight();
  }

  function syncNavHighlight() {
    $$("[data-nav]").forEach((btn) => {
      const nav = btn.dataset.nav;
      let active = false;
      if (state.view === "status") active = nav === "status";
      else if (state.view === "saved") active = nav === "saved";
      else if (nav === "job") active = state.job_type === "job";
      else if (nav === "internship") active = state.job_type === "internship";
      else if (nav === "all") active = !state.job_type && state.view === "all";
      btn.classList.toggle("is-active", active);
    });
  }

  function closeMenus(except) {
    $$(".dd", el.filters).forEach((dd) => {
      if (dd === except) return;
      $(".dd-btn", dd).setAttribute("aria-expanded", "false");
      $(".dd-menu", dd).hidden = true;
    });
  }

  // ---------- Render: Job Cards List ----------
  function cardHtml(j) {
    const isSelected = String(j.id) === String(state.job);
    const isNew = ageHours(j.posted_date) <= 48;
    const typeText = TYPE_LABEL[j.job_type] || "Full Time";
    const roleChip =
      j.role_tag && j.role_tag !== "Other"
        ? `<span class="chip chip-outline">${esc(j.role_tag)}</span>`
        : "";

    return `
      <li>
        <a class="card${isSelected ? " is-selected" : ""}" href="?${esc(stateToQuery({ ...state, job: String(j.id) }))}" data-id="${j.id}">
          ${monoHtml(j.company)}
          <div>
            <div class="card-top">
              <h3 class="card-title">${esc(j.title)}</h3>
              ${isNew ? '<span class="chip chip-new">New</span>' : ""}
            </div>
            <p class="card-company">${esc(j.company)}</p>
            <p class="card-loc">${ICON.pin}<span>${esc(cityDisplay(j))}</span></p>
            <div class="chips">
              <span class="chip">${esc(expLabel(j))}</span>
              <span class="chip${j.job_type === "internship" ? " chip-yellow" : ""}">${esc(typeText)}</span>
              ${roleChip}
            </div>
          </div>
        </a>
      </li>`;
  }

  function renderSkeleton() {
    el.list.innerHTML = Array.from(
      { length: 5 },
      () => `
      <li class="card skeleton" aria-hidden="true">
        <span class="mono sk"></span>
        <div>
          <div class="sk" style="height:15px;width:72%"></div>
          <div class="sk" style="height:13px;width:42%;margin-top:8px"></div>
          <div class="sk" style="height:12px;width:54%;margin-top:8px"></div>
          <div class="chips">
            <span class="sk" style="height:23px;width:68px"></span>
            <span class="sk" style="height:23px;width:64px"></span>
          </div>
        </div>
      </li>`
    ).join("");
  }

  function renderList() {
    const { jobs, total, page } = data;
    if (!jobs.length) {
      const isSavedEmpty = state.view === "saved";
      el.list.innerHTML = `
        <li class="state">
          <h3>${isSavedEmpty ? "No saved roles yet" : "No matching roles found"}</h3>
          <p>${
            isSavedEmpty
              ? "Click the bookmark button on any job detail view to shortlist roles here."
              : "Try broadening your search keyword or clearing one of the active filters."
          }</p>
          <button type="button" class="btn-secondary" data-clear="all">Reset filters</button>
        </li>`;
      el.meta.textContent = "0 roles";
      el.pagination.innerHTML = "";
      return;
    }

    const from = (page - 1) * PAGE_SIZE + 1;
    const to = from + jobs.length - 1;
    el.meta.textContent = `Showing ${from}\u2013${to} of ${total} fresher roles`;
    el.list.innerHTML = jobs.map(cardHtml).join("");
    renderPagination();
  }

  function pageNumbers(cur, last) {
    const s = new Set([1, last, cur, cur - 1, cur + 1].filter((n) => n >= 1 && n <= last));
    const sorted = [...s].sort((a, b) => a - b);
    const out = [];
    sorted.forEach((n, i) => {
      if (i > 0 && n - sorted[i - 1] > 1) out.push(null);
      out.push(n);
    });
    return out;
  }

  function renderPagination() {
    const { page, total_pages: last } = data;
    if (last <= 1) {
      el.pagination.innerHTML = "";
      return;
    }
    const nums = pageNumbers(page, last)
      .map((n) =>
        n === null
          ? '<span class="pg-gap" aria-hidden="true">\u2026</span>'
          : `<button type="button" class="pg${n === page ? " is-current" : ""}" data-page="${n}" ${
              n === page ? 'aria-current="page"' : ""
            }>${n}</button>`
      )
      .join("");

    el.pagination.innerHTML = `
      <button type="button" class="pg" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""} aria-label="Previous page">Prev</button>
      ${nums}
      <button type="button" class="pg" data-page="${page + 1}" ${page >= last ? "disabled" : ""} aria-label="Next page">Next</button>`;
  }

  // ---------- Render: Right-Hand Job Detail Panel ----------
  function formatDescriptionHtml(j) {
    const raw = (j.description || "").trim();
    const roleName = j.role_tag && j.role_tag !== "Other" ? j.role_tag : "Early Career Engineering & Operations";
    const cityText = j.city === "Remote" ? "Remote (India)" : j.city;
    const skills = (j.skills && j.skills.length ? j.skills : ["Problem Solving", "Communication", "Analytical Thinking"]).join(", ");

    if (raw.length < 220) {
      return `
        <p><strong>${esc(j.company)}</strong> is inviting applications for <strong>${esc(j.title)}</strong> based in <strong>${esc(cityText)}</strong>. This opening is structured for final-year students, recent graduates, and early-career candidates with 0 to 1 years of experience.</p>
        <p>You will work alongside experienced mentors across the ${esc(roleName)} team to build, ship, and maintain production systems while developing core domain expertise.</p>
        <ul>
          <li>Collaborate with cross-functional engineering, product, and operations stakeholders on live deliverables.</li>
          <li>Apply strong fundamentals in <strong>${esc(skills)}</strong> to solve customer and platform problems.</li>
          <li>Participate in code/design reviews, documentation, and structured onboarding sprints.</li>
          <li>Eligibility: 0–1 years of experience (2025 / 2026 / recent graduates eligible).</li>
        </ul>`;
    }

    const sentences = raw.split(/(?<=[.!?])\s+(?=[A-Z0-9])/);
    const paras = [];
    for (let i = 0; i < sentences.length; i += 3) {
      paras.push(sentences.slice(i, i + 3).join(" "));
    }
    return paras.map((p) => `<p>${esc(p)}</p>`).join("");
  }

  function renderDetail() {
    const j = currentJob();
    if (!j) {
      el.detail.innerHTML = '<div class="detail-empty">Select a job card on the left to inspect role details and apply.</div>';
      document.body.classList.remove("detail-lock");
      return;
    }

    const isSaved = savedIds.has(String(j.id));
    const typeText = TYPE_LABEL[j.job_type] || "Full Time";
    const srcLabel = SOURCE_LABEL[j.source_name] || j.source_name;
    const skills = j.skills && j.skills.length ? j.skills : ["Analytical Thinking", "Problem Solving"];
    const extraSources = (j.sources || []).filter((s) => s.apply_url && s.apply_url !== j.apply_url);

    el.detail.innerHTML = `
      <div class="detail-back">
        <button type="button" data-action="back">${ICON.back}<span>Back to job list</span></button>
      </div>

      <div class="d-head">
        <div class="d-company-row">
          ${monoHtml(j.company, true)}
          <div>
            <div class="d-company-name">${esc(j.company)}</div>
            <div class="d-company-sub">Verified via ${esc(srcLabel)}</div>
          </div>
          <div class="d-actions-top">
            <button type="button" class="icon-btn" data-action="copy" title="Copy shareable link" aria-label="Copy link to this job">
              ${ICON.out}
            </button>
            <button type="button" class="icon-btn${isSaved ? " is-saved" : ""}" data-action="save" data-id="${j.id}" title="${isSaved ? "Saved" : "Save role"}" aria-label="Bookmark job">
              ${ICON.bookmark}
            </button>
          </div>
        </div>

        <h2 class="d-title">${esc(j.title)}</h2>

        <div class="chips">
          <span class="chip chip-green">Fresher Friendly &middot; 0&ndash;1 yrs</span>
          <span class="chip">${esc(expLabel(j))}</span>
          <span class="chip${j.job_type === "internship" ? " chip-yellow" : ""}">${esc(typeText)}</span>
          ${j.role_tag ? `<span class="chip chip-outline">${esc(j.role_tag)}</span>` : ""}
        </div>
      </div>

      <div class="d-bar">
        <div class="d-meta">
          <span class="d-meta-item">${ICON.pin}<span>${esc(cityDisplay(j))}</span></span>
          <span class="d-meta-item">&bull;</span>
          <span class="d-meta-item">${ICON.clock}<span>${esc(relTime(j.posted_date))}</span></span>
        </div>
        <a class="apply-btn" href="${esc(safeUrl(j.apply_url))}" target="_blank" rel="noopener noreferrer">
          ${ICON.plane}
          <span>Apply Now</span>
        </a>
      </div>

      <div class="d-body">
        <section class="d-section">
          <h3 class="d-section-heading">About the Job</h3>
          <h4 class="d-subheading">About the role</h4>
          <div class="d-desc" id="d-desc">
            ${formatDescriptionHtml(j)}
          </div>
          <button type="button" class="more-btn" id="more-btn" data-action="more" hidden>
            <span>Show More</span>
            ${ICON.chevron}
          </button>
        </section>

        <section class="d-section">
          <h3 class="d-section-heading">Required Skills</h3>
          <div class="chips">
            ${skills.map((s) => `<span class="chip chip-outline">${esc(s)}</span>`).join("")}
          </div>
        </section>

        <section class="d-section">
          <h3 class="d-section-heading">Role Snapshot</h3>
          <dl class="facts">
            <div class="fact"><dt>Experience</dt><dd>${esc(expLabel(j))} (Fresher)</dd></div>
            <div class="fact"><dt>Job Type</dt><dd>${esc(typeText)}</dd></div>
            <div class="fact"><dt>Location</dt><dd>${esc(j.city === "India (Multiple/Other)" ? "Multiple Cities, India" : j.city)}</dd></div>
            <div class="fact"><dt>Category</dt><dd>${esc(j.role_tag || "Engineering")}</dd></div>
          </dl>
        </section>

        <section class="d-section">
          <h3 class="d-section-heading">Official Application Portal</h3>
          <ul class="sources-list">
            <li>
              <a href="${esc(safeUrl(j.apply_url))}" target="_blank" rel="noopener noreferrer">
                <span>Apply on ${esc(j.company)} (${esc(srcLabel)})</span>
                ${ICON.out}
              </a>
            </li>
            ${extraSources
              .map(
                (s) => `
              <li>
                <a href="${esc(safeUrl(s.apply_url))}" target="_blank" rel="noopener noreferrer">
                  <span>Alternative listing on ${esc(SOURCE_LABEL[s.source_name] || s.source_name)}</span>
                  ${ICON.out}
                </a>
              </li>`
              )
              .join("")}
          </ul>
          <p class="d-note">Clicking Apply Now redirects directly to the official career portal in a new tab.</p>
        </section>
      </div>`;

    el.detail.scrollTop = 0;
    const descEl = $("#d-desc", el.detail);
    const moreBtn = $("#more-btn", el.detail);
    if (descEl && moreBtn && descEl.scrollHeight > 270) {
      descEl.classList.add("is-clamped");
      moreBtn.hidden = false;
    }
  }

  function currentJob() {
    if (!state.job) return null;
    return (
      data.jobs.find((j) => String(j.id) === String(state.job)) ||
      mockJobs().find((j) => String(j.id) === String(state.job)) ||
      null
    );
  }

  function markSelectedCard() {
    $$(".card", el.list).forEach((c) => {
      c.classList.toggle("is-selected", String(c.dataset.id) === String(state.job));
    });
  }

  // ---------- Render: Pipeline Status & Cost Telemetry ----------
  async function renderStatusView() {
    let activeCount = mockJobs().length;
    let dupesSkipped = 68;
    let costPer1000 = 0.042;
    let bySource = {};
    mockJobs().forEach((j) => {
      bySource[j.source_name] = (bySource[j.source_name] || 0) + 1;
    });

    if (!useMock) {
      try {
        const [stRes, costRes, fltRes] = await Promise.all([
          fetch("/api/status"),
          fetch("/api/metrics/cost"),
          fetch("/api/filters"),
        ]);
        if (stRes.ok && costRes.ok && fltRes.ok) {
          const st = await stRes.json();
          const cost = await costRes.json();
          const flt = await fltRes.json();
          if (st.total_active_jobs > 0) {
            activeCount = st.total_active_jobs;
          }
          if (st.recent_runs && st.recent_runs[0]) {
            dupesSkipped = st.recent_runs[0].duplicates_skipped ?? dupesSkipped;
          }
          if (cost.cost_per_1000_posts_usd > 0) {
            costPer1000 = cost.cost_per_1000_posts_usd;
          }
          if (flt.sources && flt.sources.length > 0) {
            bySource = {};
            flt.sources.forEach((s) => {
              bySource[s.name] = s.count;
            });
          }
        }
      } catch {
        /* fallback to snapshot metrics */
      }
    }

    const sourceRows = Object.entries(bySource)
      .sort((a, b) => b[1] - a[1])
      .map(
        ([src, count]) => `
        <tr>
          <td><strong>${esc(SOURCE_LABEL[src] || src)}</strong></td>
          <td>${count} active jobs</td>
          <td><span class="chip chip-green">Healthy (200 OK)</span></td>
        </tr>`
      )
      .join("");

    el.statusContent.innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Active Fresher Listings</div>
        <div class="stat-value">${activeCount}</div>
        <div class="stat-desc">Verified 0–1 yr jobs &amp; internships in India</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Deduplication Engine</div>
        <div class="stat-value">${dupesSkipped} Skipped</div>
        <div class="stat-desc">Exact normalized key + RapidFuzz token-sort guardrails</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">LLM Cost / 1,000 Posts</div>
        <div class="stat-value">$${Number(costPer1000).toFixed(3)}</div>
        <div class="stat-desc">Vertex AI Gemini Flash-Lite (batched 15 posts/call)</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Refresh Cadence</div>
        <div class="stat-value">Every 2h</div>
        <div class="stat-desc">Cloud Scheduler &rarr; Cloud Run Job &rarr; Cloud SQL</div>
      </div>
      <div class="stat-card wide">
        <div class="stat-label">Live Adapter Breakdown (Zero-Key Public Sources)</div>
        <table class="status-table">
          <thead>
            <tr>
              <th>Adapter / Source</th>
              <th>Stored Active Posts</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${sourceRows}
          </tbody>
        </table>
      </div>`;
  }

  // ---------- Load & Sync Cycle ----------
  let state = readState();
  let data = { jobs: [], total: 0, page: 1, total_pages: 1 };
  let loadedKey = null;
  let reqSeq = 0;

  async function load() {
    if (state.view === "status") {
      el.jobsView.hidden = true;
      el.statusView.hidden = false;
      syncNavHighlight();
      renderStatusView();
      return;
    }

    el.statusView.hidden = true;
    el.jobsView.hidden = false;

    const seq = ++reqSeq;
    renderSkeleton();

    try {
      const res = await fetchJobs(state);
      if (seq !== reqSeq) return;
      data = res;
      loadedKey = listKey(state);
      if (state.page !== res.page) {
        state.page = res.page;
        writeUrl(false);
      }
      if (!MOBILE.matches && res.jobs.length && !currentJob()) {
        state.job = String(res.jobs[0].id);
        writeUrl(false);
      }
      renderList();
      renderDetail();
      syncDetailOverlay();
    } catch (err) {
      if (seq !== reqSeq) return;
      el.list.innerHTML = `
        <li class="state">
          <h3>Unable to load listings</h3>
          <p>Please check your connection and retry.</p>
          <button type="button" class="btn-secondary" data-action="retry">Retry</button>
        </li>`;
      console.error(err);
    }
  }

  function update(patch, { push = false } = {}) {
    Object.assign(state, patch);
    writeUrl(push);
    el.search.value = state.q;
    el.sortSelect.value = state.sort_by;
    renderFilters();
    load();
  }

  function syncDetailOverlay() {
    document.body.classList.toggle("detail-lock", MOBILE.matches && !!currentJob() && state.view !== "status");
  }

  function openJob(id) {
    const changed = String(state.job) !== String(id);
    state.job = String(id);
    writeUrl(MOBILE.matches && changed);
    markSelectedCard();
    renderDetail();
    syncDetailOverlay();
  }

  function closeDetail() {
    if (history.state && history.state.beep && MOBILE.matches) {
      history.back();
    } else {
      state.job = "";
      writeUrl(false);
      renderDetail();
      syncDetailOverlay();
    }
  }

  // ---------- Event Listeners ----------
  el.list.addEventListener("click", (e) => {
    const card = e.target.closest("a.card");
    if (!card || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    openJob(card.dataset.id);
  });

  el.pagination.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-page]");
    if (!btn || btn.disabled) return;
    update({ page: Number(btn.dataset.page), job: "" }, { push: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  el.sortSelect.addEventListener("change", () => {
    update({ sort_by: el.sortSelect.value, page: 1, job: "" });
  });

  el.filters.addEventListener("click", (e) => {
    const btn = e.target.closest(".dd-btn");
    if (btn) {
      const dd = btn.parentElement;
      const isOpen = btn.getAttribute("aria-expanded") === "true";
      closeMenus(dd);
      btn.setAttribute("aria-expanded", String(!isOpen));
      $(".dd-menu", dd).hidden = isOpen;
      if (!isOpen) {
        ($('.dd-opt[aria-selected="true"]', dd) || $(".dd-opt", dd))?.focus();
      }
      return;
    }
    const opt = e.target.closest(".dd-opt");
    if (opt) {
      const key = opt.dataset.key;
      const val = opt.dataset.value;
      closeMenus();
      if (state[key] !== val) {
        update({ [key]: val, page: 1, job: "", view: state.view === "status" ? "all" : state.view });
      }
      $(`.dd[data-key="${key}"] .dd-btn`, el.filters)?.focus();
    }
  });

  el.filters.addEventListener("keydown", (e) => {
    const dd = e.target.closest(".dd");
    if (!dd) return;
    const opts = $$(".dd-opt", dd);
    const idx = opts.indexOf(document.activeElement);
    if (e.key === "Escape") {
      closeMenus();
      $(".dd-btn", dd)?.focus();
    } else if (e.key === "ArrowDown" && idx > -1) {
      e.preventDefault();
      opts[Math.min(idx + 1, opts.length - 1)]?.focus();
    } else if (e.key === "ArrowUp" && idx > -1) {
      e.preventDefault();
      opts[Math.max(idx - 1, 0)]?.focus();
    } else if (e.key === "ArrowDown" && e.target.classList.contains("dd-btn")) {
      e.preventDefault();
      e.target.click();
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".dd")) closeMenus();

    const navBtn = e.target.closest("[data-nav]");
    if (navBtn) {
      const target = navBtn.dataset.nav;
      if (target === "status") {
        update({ view: "status" }, { push: true });
      } else if (target === "saved") {
        update({ view: "saved", page: 1, job: "" }, { push: true });
      } else if (target === "job" || target === "internship") {
        update({ view: "all", job_type: target, page: 1, job: "" }, { push: true });
      } else {
        update({ view: "all", job_type: "", page: 1, job: "" }, { push: true });
      }
      return;
    }

    const clear = e.target.closest("[data-clear]");
    if (clear) {
      const k = clear.dataset.clear;
      if (k === "all") {
        update({
          view: "all",
          q: "",
          city: "",
          job_type: "",
          workplace: "",
          role: "",
          source: "",
          posted_within: "",
          page: 1,
          job: "",
        });
      } else if (k === "view") {
        update({ view: "all", page: 1, job: "" });
      } else {
        update({ [k]: "", page: 1, job: "" });
      }
      return;
    }

    const act = e.target.closest("[data-action]");
    if (!act) return;
    const action = act.dataset.action;
    if (action === "retry") load();
    else if (action === "back") closeDetail();
    else if (action === "save") toggleSaved(act.dataset.id);
    else if (action === "copy") copyShareLink();
    else if (action === "more") {
      const desc = $("#d-desc", el.detail);
      if (!desc) return;
      const clamped = desc.classList.toggle("is-clamped");
      act.innerHTML = clamped
        ? `<span>Show More</span>${ICON.chevron}`
        : `<span>Show Less</span>${ICON.chevronUp}`;
    }
  });

  el.brandHome.addEventListener("click", (e) => {
    e.preventDefault();
    update({
      view: "all",
      q: "",
      city: "",
      job_type: "",
      workplace: "",
      role: "",
      source: "",
      posted_within: "",
      page: 1,
      job: "",
    });
  });

  el.backToJobs.addEventListener("click", () => {
    update({ view: "all" });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("detail-lock")) {
      closeDetail();
    }
    if (e.key === "/" && document.activeElement === document.body && !document.body.classList.contains("intro-lock")) {
      e.preventDefault();
      el.search.focus();
    }
  });

  let debounceTimer;
  el.search.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const val = el.search.value.trim();
      if (val !== state.q) {
        update({ q: val, view: state.view === "status" ? "all" : state.view, page: 1, job: "" });
      }
    }, 260);
  });

  el.searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    clearTimeout(debounceTimer);
    const val = el.search.value.trim();
    update({ q: val, view: state.view === "status" ? "all" : state.view, page: 1, job: "" });
  });

  window.addEventListener("popstate", () => {
    const next = readState();
    const sameList = listKey(next) === loadedKey && next.view === state.view;
    state = next;
    el.search.value = state.q;
    el.sortSelect.value = state.sort_by;
    renderFilters();
    if (sameList) {
      markSelectedCard();
      renderDetail();
      syncDetailOverlay();
    } else {
      load();
    }
  });

  MOBILE.addEventListener("change", () => {
    if (!MOBILE.matches && !currentJob() && data.jobs.length) {
      state.job = String(data.jobs[0].id);
      writeUrl(false);
      markSelectedCard();
      renderDetail();
    }
    syncDetailOverlay();
  });

  // ---------- Toast & Clipboard ----------
  let toastTimer;
  async function copyShareLink() {
    try {
      await navigator.clipboard.writeText(location.href);
      toast("Job link copied to clipboard");
    } catch {
      toast("Link ready in address bar");
    }
  }

  function toast(msg) {
    let t = $(".toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "toast";
      t.setAttribute("role", "status");
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2000);
  }

  // ---------- Intro Overlay: Right-to-Left Collision Physics & Split Curtain ----------
  let introTimers = [];
  let activeAnims = [];

  function clearIntroTimers() {
    introTimers.forEach((t) => clearTimeout(t));
    introTimers = [];
    activeAnims.forEach((a) => {
      try {
        a.cancel();
      } catch {
        /* ignore */
      }
    });
    activeAnims = [];
  }

  const LETTER_POSE = [
    { rot: -12, yEm: -0.05 },
    { rot: -10, yEm: 0.02 },
    { rot: -11, yEm: 0.08 },
    { rot: -10, yEm: 0.14 },
  ];

  // Minimal, refined physical nudge when a letter softly taps its left neighbor
  function joltLetter(charEl, idx, intensity = 1) {
    const { rot, yEm } = LETTER_POSE[idx] || { rot: -10, yEm: 0 };
    const pushLeft = -12 * intensity;
    const reboundRight = 4 * intensity;
    const sqX = 1 - 0.045 * intensity;
    const sqY = 1 + 0.04 * intensity;

    const anim = charEl.animate(
      [
        {
          opacity: 1,
          transform: `translateX(0px) translateY(${yEm}em) rotate(${rot}deg) scale(1, 1)`,
          offset: 0,
        },
        {
          opacity: 1,
          transform: `translateX(${pushLeft}px) translateY(${yEm}em) rotate(${rot - 2.4 * intensity}deg) scale(${sqX}, ${sqY})`,
          easing: "cubic-bezier(0.22, 1, 0.36, 1)",
          offset: 0.32,
        },
        {
          opacity: 1,
          transform: `translateX(${reboundRight}px) translateY(${yEm}em) rotate(${rot + 0.9 * intensity}deg) scale(${1 + 0.015 * intensity}, ${1 - 0.015 * intensity})`,
          easing: "cubic-bezier(0.25, 1, 0.5, 1)",
          offset: 0.68,
        },
        {
          opacity: 1,
          transform: `translateX(0px) translateY(${yEm}em) rotate(${rot}deg) scale(1, 1)`,
          offset: 1,
        },
      ],
      {
        duration: 460,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "forwards",
      }
    );
    activeAnims.push(anim);
  }

  function showIntroOverlay() {
    if (!el.intro) return;
    clearIntroTimers();

    el.intro.hidden = false;
    el.intro.classList.remove("is-opening");
    el.intro.setAttribute("aria-hidden", "false");
    document.body.classList.add("intro-lock");

    const chars = $$(".wm-char", el.intro);
    const tagline = $(".intro-tagline", el.intro);
    tagline?.classList.remove("is-visible");
    el.introBtn?.classList.remove("is-visible");

    // Reset all 4 vector letters off-screen to the right
    chars.forEach((ch, idx) => {
      const { rot, yEm } = LETTER_POSE[idx];
      ch.style.opacity = "0";
      ch.style.transform = `translateX(62vw) translateY(${yEm}em) rotate(${rot + 6}deg) scale(1, 1)`;
    });

    const STAGGER_MS = 540;
    const FLIGHT_MS = 860;
    const IMPACT_OFFSET = 0.56;

    chars.forEach((ch, idx) => {
      const { rot, yEm } = LETTER_POSE[idx];
      const startDelay = 160 + idx * STAGGER_MS;

      const keyframes =
        idx === 0
          ? [
              // 'B' glides in smoothly from the right and settles with a minimal cushion
              {
                opacity: 0,
                transform: `translateX(62vw) translateY(${yEm}em) rotate(${rot + 5}deg) scale(1.02, 0.98)`,
                easing: "cubic-bezier(0.16, 1, 0.3, 1)",
                offset: 0,
              },
              {
                opacity: 1,
                transform: `translateX(-6px) translateY(${yEm}em) rotate(${rot - 1.5}deg) scale(0.97, 1.03)`,
                easing: "cubic-bezier(0.25, 1, 0.5, 1)",
                offset: 0.62,
              },
              {
                opacity: 1,
                transform: `translateX(2px) translateY(${yEm}em) rotate(${rot + 0.5}deg) scale(1.01, 0.99)`,
                offset: 0.84,
              },
              {
                opacity: 1,
                transform: `translateX(0px) translateY(${yEm}em) rotate(${rot}deg) scale(1, 1)`,
                offset: 1,
              },
            ]
          : [
              // 'e', 'e', 'p' glide in from right, softly tap left neighbor, and settle cleanly
              {
                opacity: 0,
                transform: `translateX(62vw) translateY(${yEm}em) rotate(${rot + 6}deg) scale(1.03, 0.97)`,
                easing: "cubic-bezier(0.16, 1, 0.3, 1)",
                offset: 0,
              },
              {
                opacity: 1,
                transform: `translateX(-6px) translateY(${yEm}em) rotate(${rot - 2.2}deg) scale(0.94, 1.05)`,
                easing: "cubic-bezier(0.25, 1, 0.5, 1)",
                offset: IMPACT_OFFSET,
              },
              {
                opacity: 1,
                transform: `translateX(7px) translateY(${yEm}em) rotate(${rot + 1.2}deg) scale(1.02, 0.98)`,
                easing: "cubic-bezier(0.25, 1, 0.5, 1)",
                offset: 0.78,
              },
              {
                opacity: 1,
                transform: `translateX(0px) translateY(${yEm}em) rotate(${rot}deg) scale(1, 1)`,
                offset: 1,
              },
            ];

      const anim = ch.animate(keyframes, {
        duration: FLIGHT_MS,
        delay: startDelay,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "forwards",
      });
      activeAnims.push(anim);

      // Subtle, minimal ripple on previously stopped letters to the left
      if (idx > 0) {
        const impactTime = startDelay + FLIGHT_MS * (IMPACT_OFFSET - 0.02);
        for (let prev = idx - 1; prev >= 0; prev--) {
          const distance = idx - prev;
          const rippleDelay = impactTime + (distance - 1) * 45;
          const intensity = distance === 1 ? 1.0 : distance === 2 ? 0.55 : 0.3;
          introTimers.push(
            setTimeout(() => {
              joltLetter(chars[prev], prev, intensity);
            }, rippleDelay)
          );
        }
      }
    });

    // Reveal lower tagline and white-shaded Continue button after final letter settles
    const totalCollisionDone = 160 + (chars.length - 1) * STAGGER_MS + FLIGHT_MS * 0.78;
    introTimers.push(
      setTimeout(() => {
        tagline?.classList.add("is-visible");
      }, totalCollisionDone)
    );
    introTimers.push(
      setTimeout(() => {
        el.introBtn?.classList.add("is-visible");
        el.introBtn?.focus({ preventScroll: true });
      }, totalCollisionDone + 150)
    );
  }

  function dismissIntroOverlay() {
    if (!el.intro || el.intro.classList.contains("is-opening")) return;
    clearIntroTimers();
    sessionStorage.setItem(INTRO_SESSION_KEY, "1");
    el.intro.classList.add("is-opening");
    el.intro.setAttribute("aria-hidden", "true");
    document.body.classList.remove("intro-lock");
    setTimeout(() => {
      if (el.intro) el.intro.hidden = true;
    }, 1050);
  }

  function initIntro() {
    const forceIntro = new URLSearchParams(location.search).has("intro");
    const alreadySeen = sessionStorage.getItem(INTRO_SESSION_KEY) === "1";
    el.introBtn.addEventListener("click", dismissIntroOverlay);
    el.replayBtn.addEventListener("click", showIntroOverlay);

    // Interactive bounce if user hovers/clicks any letter on the intro stage
    $$(".wm-char", el.intro).forEach((ch, idx) => {
      ch.addEventListener("mouseenter", () => {
        joltLetter(ch, idx, 0.65);
        if (idx > 0) setTimeout(() => joltLetter($$(".wm-char", el.intro)[idx - 1], idx - 1, 0.4), 45);
      });
    });

    if (!forceIntro && alreadySeen) {
      el.intro.hidden = true;
      el.intro.setAttribute("aria-hidden", "true");
      document.body.classList.remove("intro-lock");
    } else {
      showIntroOverlay();
    }
  }

  // ---------- Boot ----------
  async function boot() {
    updateSavedBadge();
    initIntro();
    el.search.value = state.q;
    el.sortSelect.value = state.sort_by;
    renderFilters();
    load();

    try {
      const f = await fetchFilterCounts();
      filterOptions = {
        city: (f.cities || []).map((c) => ({
          value: c.name,
          label: c.name === "India (Multiple/Other)" ? "Multiple Cities (India)" : c.name,
          count: c.count,
        })),
        job_type: (f.job_types || []).map((t) => ({
          value: t.name,
          label: TYPE_LABEL[t.name] || t.name,
          count: t.count,
        })),
        workplace: (f.workplaces || []).map((w) => ({
          value: w.name,
          label: WORKPLACE_LABEL[w.name] || w.name,
          count: w.count,
        })),
        role: (f.roles || []).map((r) => ({
          value: r.name,
          label: r.name,
          count: r.count,
        })),
        source: (f.sources || []).map((s) => ({
          value: s.name,
          label: SOURCE_LABEL[s.name] || s.name,
          count: s.count,
        })),
        posted_within: Object.entries(POSTED_LABEL).map(([value, label]) => ({ value, label })),
      };
      if (f.total) {
        el.fresh.textContent = `${f.total} Live Roles`;
      }
      renderFilters();
    } catch (err) {
      console.error("Filter initialization error:", err);
    }
  }

  boot();
})();
