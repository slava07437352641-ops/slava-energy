// Bootstrap for the Public objections & discussions dashboard (Pilot v0.1).
import { readState, writeState } from "./url-state.js";
import { applyAll, facetCounts, FACETS, TECH_CATEGORIES } from "./filters.js";
import { renderFeed, renderDetail, renderMirror } from "./feed.js";

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
  footerMirrorCaveat: document.getElementById("pd-footer-mirror-caveat"),
  newsPanel: document.querySelector(".pd-news-panel"),
  loadMoreWrap: document.getElementById("pd-load-more-wrap"),
  loadMore: document.getElementById("pd-load-more"),
};

const PAGE_SIZE = 60;

let ALL = [];
let NEWS_IDS = new Set();
let MIRROR_IDS = new Set();
let state = readState();
let visibleCount = PAGE_SIZE;

init();

async function init() {
  els.feed.innerHTML = `<div class="pd-empty">Loading discussions&hellip;</div>`;

  let index;
  try {
    const res = await fetch("data/discussions-index.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    index = await res.json();
  } catch {
    els.feed.innerHTML = `
      <div class="pd-empty">
        Discussions could not be loaded. Check your connection and try again.<br>
        <button id="pd-retry" type="button" class="pd-retry">Retry</button>
      </div>`;
    document.getElementById("pd-retry")?.addEventListener("click", init);
    return;
  }
  ALL = index.records;

  // Track whatever the Recent News panel is showing (news.js, same
  // NEWS_PANEL_LIMIT) so the default browse view can exclude it (no record
  // rendered twice on the page). ALL itself stays the full dataset --
  // search must still be able to find these records; only the panel is
  // hidden while searching (see apply()), not removed from the dataset.
  try {
    const nres = await fetch("data/news-index.json", { cache: "no-cache" });
    if (nres.ok) {
      const newsIndex = await nres.json();
      NEWS_IDS = new Set((newsIndex.records || []).slice(0, NEWS_PANEL_LIMIT).map((r) => r.id));
    }
  } catch {
    // news panel data unavailable -- main feed just shows everything, no dedup needed
  }

  // Manually-curated original-post mirrors (see data/mirror/README.md) -- opt-in
  // per record, never populated by an automated fetch.
  try {
    const mres = await fetch("data/mirror/manifest.json", { cache: "no-cache" });
    if (mres.ok) MIRROR_IDS = new Set(await mres.json());
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
  els.loadMore?.addEventListener("click", () => {
    visibleCount += PAGE_SIZE;
    apply();
    els.loadMore.focus();
  });

  buildTechChips();
  apply({ initial: true });

  if (state.sel) select(state.sel, { silent: true });
}

// Single-select: clicking a chip REPLACES the current selection rather than
// adding to it. The previous OR-multi-select behaviour meant clicking a
// second chip left both showing active at once (reported live: Onshore
// Wind + BESS both highlighted after clicking each in turn) -- clicking the
// already-active chip, or "All", clears back to no filter.
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

function apply({ initial = false } = {}) {
  const isSearching = state.q.trim().length > 0;
  // The default browse view excludes whatever Recent Posts is showing (so
  // nothing renders twice on the page) -- but that panel is hidden the
  // moment a search is active, so the exclusion no longer serves its
  // purpose then and would otherwise make the newest posts unsearchable.
  const pool = isSearching ? ALL : ALL.filter((r) => !NEWS_IDS.has(r.id));
  const filtered = applyAll(pool, state).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  const counts = facetCounts(pool, state);

  // Recent Posts is a fixed, unfiltered curated panel -- it never reacts to
  // search, so leaving it visible while searching makes real (possibly rare)
  // matches easy to miss below it. Hide it whenever a search is active.
  if (els.newsPanel) els.newsPanel.hidden = isSearching;

  // tech chip active states
  els.tech.querySelectorAll(".pd-chip").forEach((b) => {
    const v = b.dataset.tech;
    b.classList.toggle("is-active", v ? state.tech.includes(v) : state.tech.length === 0);
    if (v) {
      const n = counts.tech[v] || 0;
      b.dataset.count = n;
    }
  });

  const shown = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > shown.length;

  // The feed only ever rendered a flat 400-record slice with no indication
  // more existed -- the header could say "2,317 discussions" while only 400
  // were reachable. Now the count says "Showing N of Total" whenever a page
  // boundary is actually hiding records, and a Load more control reveals
  // the rest in place.
  els.count.textContent = hasMore
    ? `Showing ${shown.length.toLocaleString()} of ${filtered.length.toLocaleString()} discussion${filtered.length === 1 ? "" : "s"}`
    : `${filtered.length.toLocaleString()} discussion${filtered.length === 1 ? "" : "s"}`;

  renderFeed(els.feed, shown, { selectedId: state.sel, onSelect: (id) => select(id), mirrorIds: MIRROR_IDS });

  if (els.loadMoreWrap) {
    els.loadMoreWrap.hidden = !hasMore;
    if (hasMore) els.loadMore.textContent = `Load more (${(filtered.length - shown.length).toLocaleString()} remaining)`;
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
    const res = await fetch(`data/mirror/${id}.json`, { cache: "no-cache" });
    if (!res.ok) return;
    const mirror = await res.json();
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
