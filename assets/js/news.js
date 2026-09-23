// Render news panel from news-index.json (U4 of feat-daily-news-panel-plan.md)
// Loads Scotland Against Spin and APR Scotland posts and displays them in the news panel.

import { renderFeed, scrollFeedTo, renderDetail } from "./feed.js";

// Single source of truth for how many items the Recent News panel shows --
// main.js imports this too, to exclude the same IDs from the main feed
// below so no post is ever rendered twice on the page (see html-rules-v1.1
// Rule 3, no duplicate posts).
export const NEWS_PANEL_LIMIT = 4;

/**
 * Load and render the news panel from news-index.json.
 * @param {string} dataPath - path to news-index.json (default: "data/news-index.json")
 * @returns {Promise<void>}
 */
export async function loadAndRenderNews(dataPath = "data/news-index.json") {
  const container = document.getElementById("pd-news-feed");
  if (!container) {
    console.warn("[news.js] #pd-news-feed container not found, skipping news panel load");
    return;
  }

  try {
    const response = await fetch(dataPath);
    if (!response.ok) {
      throw new Error(`fetch failed: ${response.status} ${response.statusText}`);
    }

    const newsIndex = await response.json();
    const records = (newsIndex.records || []).slice(0, NEWS_PANEL_LIMIT);

    if (records.length === 0) {
      container.innerHTML = '<div class="pd-empty">No recent news available.</div>';
      return;
    }

    // Render news cards using the same pattern as the main feed
    // but with no search/filter functionality (read-only news panel)
    renderNewsCards(container, records);
  } catch (error) {
    console.error("[news.js] failed to load news:", error);
    container.innerHTML = `<div class="pd-empty">Could not load news panel. ${error.message}</div>`;
  }
}

/**
 * Render news cards in the news panel container.
 * Reuses styling from feed.js (pd-card, pd-card-title, pd-card-meta, etc.)
 * but with no interactivity or selection handling.
 *
 * @param {HTMLElement} container
 * @param {Array<object>} records - news records from news-index.json
 */
function renderNewsCards(container, records) {
  container.innerHTML = "";
  const detailPanel = document.getElementById("pd-detail");

  for (const r of records) {
    const card = document.createElement("article");
    card.className = "pd-card";
    card.dataset.id = r.id;

    const thumb = (r.photos && r.photos[0]) || r.previewImage;
    const excerpt = cardExcerpt(r);
    const mediaLabel = r.mediaCount ? ` · ${r.mediaCount} photo${r.mediaCount > 1 ? "s" : ""}` : "";

    card.innerHTML = `
      ${thumb ? `<img class="pd-card-thumb" src="${safeUrl(thumb)}" alt="" loading="lazy">` : ""}
      <h3 class="pd-card-title">${escapeHtml(r.title)}</h3>
      ${excerpt ? `<p class="pd-card-summary">${escapeHtml(excerpt)}</p>` : ""}
      <div class="pd-card-meta">
        ${(r.categories || []).map((c) => `<span class="pd-tag pd-tag--tech">${escapeHtml(c)}</span>`).join("")}
        ${(r.topics || []).slice(0, 3).map((t) => `<span class="pd-tag">${escapeHtml(t)}</span>`).join("")}
      </div>
      <div class="pd-card-source">Source: ${escapeHtml(r.source.label)}${mediaLabel}</div>
    `;

    if (detailPanel) {
      card.addEventListener("click", () => {
        document.body.classList.add("pd-showing-detail");
        renderDetail(detailPanel, r, {
          hasMirror: false,
          onBack: () => document.body.classList.remove("pd-showing-detail"),
        });
      });
    }

    container.appendChild(card);
  }
}

// ---- Helper functions (same as in feed.js) ----

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function safeUrl(u) {
  try {
    const parsed = new URL(String(u), window.location.href);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "#";
  } catch {
    return "#";
  }
}

function truncate(s, n) {
  return s.length <= n ? s : s.slice(0, n).replace(/\s+\S*$/, "") + "…";
}

function cardExcerpt(r) {
  if (r.summary) return r.summary;
  if (r.bodyText) return truncate(r.bodyText.replace(/\s+/g, " ").trim(), 220);
  return "";
}

// Auto-load news panel on DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => loadAndRenderNews());
} else {
  loadAndRenderNews().catch((e) => console.error("[news.js] failed to load news on ready:", e));
}
