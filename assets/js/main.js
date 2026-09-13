// Bootstrap for the Public objections & discussions dashboard (Pilot v0.1).
import { readState, writeState } from "./url-state.js?v=20260913d";
import { applyAll, facetCounts, FACETS, TECH_CATEGORIES } from "./filters.js?v=20260913d";
import { renderFeed, scrollFeedTo, renderDetail, renderMirror } from "./feed.js?v=20260913d";
import { DiscussionMap } from "./map.js?v=20260913d";

const els = {
  feed: document.getElementById("pd-feed"),
  mapWrap: document.getElementById("pd-map-wrap"),
  map: document.getElementById("pd-map"),
  detail: document.getElementById("pd-detail"),
  search: document.getElementById("pd-search"),
  tech: document.getElementById("pd-tech"),
  count: document.getElementById("pd-count"),
  fit: document.getElementById("pd-fit"),
  range: document.getElementById("pd-range"),
  infraToggle: document.getElementById("pd-infra-toggle"),
  clusterBanner: document.getElementById("pd-cluster-banner"),
  clusterBannerText: document.getElementById("pd-cluster-banner-text"),
  clusterClear: document.getElementById("pd-cluster-clear"),
  footerMirrorCaveat: document.getElementById("pd-footer-mirror-caveat"),
};

let ALL = [];
let MIRROR_IDS = new Set();
let state = readState();
let dmap;
let clusterPickIds = null; // set of record ids when the user has clicked a map cluster that can't be zoomed apart

init();

async function init() {
  const res = await fetch("data/discussions-index.json", { cache: "no-cache" });
  const index = await res.json();
  ALL = index.records;

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

  dmap = new DiscussionMap(els.map, {
    onSelect: (id, opts) => select(id, opts),
    onClusterOpen: (props) => showClusterPicks(props.map((p) => p.id)),
  });
  dmap.onMoveEnd((view) => {
    state.view = view;
    writeState(state);
  });

  els.search.value = state.q;
  els.range.value = state.range;
  els.search.addEventListener("input", debounce(() => {
    state.q = els.search.value.trim();
    state.sel = null;
    clusterPickIds = null;
    apply();
  }, 180));
  els.range.addEventListener("change", () => {
    state.range = els.range.value;
    clusterPickIds = null;
    apply();
  });
  els.fit.addEventListener("click", () => dmap.fitResults());
  els.clusterClear.addEventListener("click", () => {
    clusterPickIds = null;
    apply();
  });

  els.infraToggle.querySelectorAll("input[data-infra]").forEach((cb) => {
    cb.addEventListener("change", () => dmap.setInfraLayerVisible(cb.dataset.infra, cb.checked));
  });

  buildTechChips();
  apply({ initial: true });

  if (state.sel) select(state.sel, { silent: true });
}

function buildTechChips() {
  els.tech.innerHTML =
    `<button class="pd-chip" data-tech="" type="button">All</button>` +
    TECH_CATEGORIES.map((c) => `<button class="pd-chip" data-tech="${c}" type="button">${c}</button>`).join("");
  els.tech.querySelectorAll(".pd-chip").forEach((b) => {
    b.addEventListener("click", () => {
      const v = b.dataset.tech;
      if (!v) state.tech = [];
      else state.tech = state.tech.includes(v) ? state.tech.filter((x) => x !== v) : [...state.tech, v];
      state.sel = null;
      clusterPickIds = null;
      apply();
    });
  });
}

function apply({ initial = false } = {}) {
  const filtered = applyAll(ALL, state);
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

  els.count.textContent = `${filtered.length.toLocaleString()} discussion${filtered.length === 1 ? "" : "s"}`;

  if (clusterPickIds) {
    const picks = filtered.filter((r) => clusterPickIds.has(r.id));
    els.clusterBanner.hidden = false;
    els.clusterBannerText.textContent = `Showing ${picks.length} discussion${picks.length === 1 ? "" : "s"} at this map point`;
    renderFeed(els.feed, picks, { selectedId: state.sel, onSelect: (id) => select(id), mirrorIds: MIRROR_IDS });
  } else {
    els.clusterBanner.hidden = true;
    renderFeed(els.feed, filtered.slice(0, 400), { selectedId: state.sel, onSelect: (id) => select(id), mirrorIds: MIRROR_IDS });
  }

  dmap.setData(filtered);
  if (!initial) dmap.autoFit();

  writeState(state);
}

// A map cluster whose members share the same (or near-identical) coordinate
// can never be zoomed apart -- list its posts in the sidebar so they can be
// picked directly instead. Cleared by any new search/filter/range change.
function showClusterPicks(ids) {
  clusterPickIds = new Set(ids);
  state.sel = null;
  apply();
}

function select(id, { fromMap = false, silent = false } = {}) {
  const rec = ALL.find((r) => r.id === id);
  if (!rec) return;
  state.sel = id;
  els.mapWrap.classList.add("pd-showing-detail");
  renderDetail(els.detail, rec, {
    hasMirror: MIRROR_IDS.has(id),
    onBack: () => {
      state.sel = null;
      els.mapWrap.classList.remove("pd-showing-detail");
      writeState(state);
      apply();
    },
  });
  if (MIRROR_IDS.has(id)) loadMirror(id);
  dmap.select(id);
  // reflect selection in feed
  els.feed.querySelectorAll(".pd-card").forEach((c) => c.classList.toggle("is-selected", c.dataset.id === id));
  if (fromMap) scrollFeedTo(els.feed, id);
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
