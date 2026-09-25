// Bootstrap for the Public objections & discussions dashboard (Pilot v0.1).
import { readState, writeState } from "./url-state.js";
import { applyAll, facetCounts, FACETS, TECH_CATEGORIES } from "./filters.js";
import { renderFeed, scrollFeedTo, renderDetail, renderMirror } from "./feed.js";
import { KNOWN_PROJECTS } from "./project-aliases.js";

// Must match news.js's NEWS_PANEL_LIMIT -- kept as a separate constant
// rather than a cross-module import so this file never depends on
// news.js's auto-init side effect running exactly once (see html-rules-v1.1
// Rule 3, no duplicate posts: the Recent News panel and the main feed below
// must never show the same record).
const NEWS_PANEL_LIMIT = 4;

const els = {
  feed: document.getElementById("pd-feed"),
  detail: document.getElementById("pd-detail"),
  search: document.getElementById("pd-search"),
  tech: document.getElementById("pd-tech"),
  count: document.getElementById("pd-count"),
  range: document.getElementById("pd-range"),
  project: document.getElementById("pd-project"),
  footerMirrorCaveat: document.getElementById("pd-footer-mirror-caveat"),
  loading: document.getElementById("pd-loading"),
  error: document.getElementById("pd-error"),
  errorRetry: document.getElementById("pd-error-retry"),
  main: document.getElementById("pd-main"),
  newsPanel: document.getElementById("pd-news-panel"),
  loadMoreWrap: document.getElementById("pd-load-more-wrap"),
  loadMore: document.getElementById("pd-load-more"),
};

const PAGE_SIZE = 60;

let ALL = [];
let MIRROR_IDS = new Set();
let state = readState();
let visibleCount = PAGE_SIZE;

init();

async function init() {
  showLoading();
  try {
    const index = await loadJson("data/discussions-index.json");
    ALL = index.records;
  } catch (err) {
    showError(err);
    return;
  }

  // Exclude whatever the Recent Posts panel is showing (news.js, same
  // NEWS_PANEL_LIMIT) so no record is ever rendered twice on the page.
  try {
    const newsIndex = await loadJson("data/news-index.json");
    const newsIds = new Set((newsIndex.records || []).slice(0, NEWS_PANEL_LIMIT).map((r) => r.id));
    if (newsIds.size) ALL = ALL.filter((r) => !newsIds.has(r.id));
  } catch {
    // news panel data unavailable -- main feed just shows everything, no dedup needed
  }

  // Manually-curated original-post mirrors (see data/mirror/README.md) -- opt-in
  // per record, never populated by an automated fetch.
  try {
    MIRROR_IDS = new Set(await loadJson("data/mirror/manifest.json"));
  } catch {
    MIRROR_IDS = new Set();
  }
  // The privacy footer's blanket "no comments/identities published" claim
  // stops being accurate the moment even one mirror exists -- show the
  // caveat immediately, not once coverage reaches any particular size
  // (plan U10-D; unlike the "featured" badge wording, this is a factual
  // accuracy question, not a framing-at-scale one).
  els.footerMirrorCaveat.hidden = MIRROR_IDS.size === 0;

  els.search.value = state.q;
  els.range.value = state.range;
  els.search.addEventListener("input", debounce(() => {
    state.q = els.search.value.trim();
    state.sel = null;
    visibleCount = PAGE_SIZE;
    apply();
  }, 180));
  els.range.addEventListener("change", () => {
    state.range = els.range.value;
    visibleCount = PAGE_SIZE;
    apply();
  });
  els.project.addEventListener("change", () => {
    state.project = els.project.value ? [els.project.value] : [];
    visibleCount = PAGE_SIZE;
    apply();
  });
  els.loadMore.addEventListener("click", () => {
    visibleCount += PAGE_SIZE;
    apply();
    els.loadMore.focus();
  });

  buildTechChips();
  buildProjectOptions();
  showLoaded();
  apply({ initial: true });

  if (state.sel) select(state.sel, { silent: true });
}

// A thin wrapper so every fetch site gets the same "network/parse failure"
// handling -- a missing or malformed JSON response throws, which init()
// catches and turns into the visible error/retry state (requirement: clear
// loading and failure messages, with a retry path if the main data can't load).
async function loadJson(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

function showLoading() {
  els.loading.hidden = false;
  els.error.hidden = true;
  els.main.hidden = true;
}
function showLoaded() {
  els.loading.hidden = true;
  els.error.hidden = true;
  els.main.hidden = false;
}
function showError(err) {
  els.loading.hidden = true;
  els.main.hidden = true;
  els.error.hidden = false;
  els.error.querySelector("[data-error-message]").textContent =
    "Could not load discussion data. " + (err?.message || "Unknown error.");
}
els.errorRetry?.addEventListener("click", () => init());

// Single-select: clicking a category chip REPLACES the current selection,
// it never adds to it. Clicking the already-active chip (or "All") clears
// back to no filter. Two chips both showing active at once was a reported
// bug (multi-select OR-filter behaviour reads as "these two got stuck
// selected together") -- this is the fix.
function buildTechChips() {
  els.tech.innerHTML =
    `<button class="pd-chip" data-tech="" type="button">All</button>` +
    TECH_CATEGORIES.map((c) => `<button class="pd-chip" data-tech="${c}" type="button">${c}</button>`).join("");
  els.tech.querySelectorAll(".pd-chip").forEach((b) => {
    b.addEventListener("click", () => {
      const v = b.dataset.tech;
      if (!v || state.tech.includes(v)) state.tech = [];
      else state.tech = [v];
      state.sel = null;
      visibleCount = PAGE_SIZE;
      apply();
    });
  });
}

// Options list is the reviewed project catalogue (project-aliases.js), never
// derived by scanning free text -- filtering by project only ever matches
// records whose project field was already corroborated during enrichment.
function buildProjectOptions() {
  els.project.innerHTML =
    `<option value="">All projects</option>` +
    KNOWN_PROJECTS.map((p) => `<option value="${p.canonical}">${p.canonical}</option>`).join("");
}

// A search or any active filter narrows the MAIN feed but the Recent Posts
// panel is a fixed, unrelated set of the most recent posts across all
// sources -- leaving it visible during a search reads as "these 4 unrelated
// posts also matched", which they don't. Hiding it while any filter is
// active removes that ambiguity; it returns as soon as the view is back to
// the unfiltered default.
function isFiltering(s) {
  return Boolean(s.q || s.tech.length || s.topic.length || s.council.length || s.project.length || s.range !== "6m");
}

function apply({ initial = false } = {}) {
  const filtered = applyAll(ALL, state).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  const counts = facetCounts(ALL, state);

  // tech chip active states
  els.tech.querySelectorAll(".pd-chip").forEach((b) => {
    const v = b.dataset.tech;
    b.classList.toggle("is-active", v ? state.tech.includes(v) : state.tech.length === 0);
    if (v) {
      const n = counts.tech[v] || 0;
      b.dataset.count = n;
    }
  });
  els.project.value = state.project?.[0] || "";

  const filtering = isFiltering(state);
  els.newsPanel.hidden = filtering;

  const shown = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > shown.length;

  // Only say "Showing N of Total" when a page boundary actually hides
  // records -- once everything filtered is on screen, the plain count is
  // unambiguous on its own and doesn't need the extra clause.
  els.count.textContent = hasMore
    ? `Showing ${shown.length.toLocaleString()} of ${filtered.length.toLocaleString()} discussion${filtered.length === 1 ? "" : "s"}`
    : `${filtered.length.toLocaleString()} discussion${filtered.length === 1 ? "" : "s"}`;

  renderFeed(els.feed, shown, { selectedId: state.sel, onSelect: (id) => select(id), mirrorIds: MIRROR_IDS });

  els.loadMoreWrap.hidden = !hasMore;
  if (hasMore) {
    els.loadMore.textContent = `Load more (${(filtered.length - shown.length).toLocaleString()} remaining)`;
  }

  writeState(state);
}

function select(id, { silent = false } = {}) {
  const rec = ALL.find((r) => r.id === id);
  if (!rec) return;
  state.sel = id;
  document.body.classList.add("pd-showing-detail");
  renderDetail(els.detail, rec, {
    hasMirror: MIRROR_IDS.has(id),
    onBack: () => {
      state.sel = null;
      document.body.classList.remove("pd-showing-detail");
      writeState(state);
      apply();
    },
  });
  if (MIRROR_IDS.has(id)) loadMirror(id);
  // reflect selection in feed
  els.feed.querySelectorAll(".pd-card").forEach((c) => c.classList.toggle("is-selected", c.dataset.id === id));
  if (!silent) writeState(state);
}

async function loadMirror(id) {
  try {
    const mirror = await loadJson(`data/mirror/${id}.json`);
    if (state.sel === id) renderMirror(els.detail, mirror, { totalMirrorCount: MIRROR_IDS.size });
  } catch {
    // no mirror available -- detail panel simply has no "Original post" section
  }
}

function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}
