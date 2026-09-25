// Dated Outlook-style discussion feed + detailed right-hand view (spec §3, §25).
// Cards show ONLY available fields -- no author, no "no data", no empty rows.

const fmtHeader = (iso) =>
  new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

function field(label, value) {
  if (!value) return "";
  return `<div class="pd-field"><span>${label}</span> ${escapeHtml(value)}</div>`;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// Only allow http/https hrefs -- neutralises javascript:/data: URLs that
// escapeHtml alone would let through.
function safeUrl(u) {
  try {
    const parsed = new URL(String(u), window.location.href);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "#";
  } catch {
    return "#";
  }
}
function hostOf(u) {
  try {
    return new URL(u).hostname;
  } catch {
    return u;
  }
}

// externalSource is stored as a mechanically title-cased domain fragment
// (e.g. "Heraldscotland", "Bbc") -- this is a display-only cleanup of that
// same value for the ~40 most common sources in the archive, never a new
// fact. Anything not listed falls back to the stored value unchanged.
const PRETTY_SOURCE = {
  Telegraph: "The Telegraph",
  Scotsman: "The Scotsman",
  Bbc: "BBC",
  Heraldscotland: "The Herald (Scotland)",
  Thenational: "The National",
  Pressreader: "PressReader",
  Youtube: "YouTube",
  Energyconsents: "Energy Consents (Scottish Government)",
  "Davidturver Substack": "David Turver (Substack)",
  Energyvoice: "Energy Voice",
  Dailymail: "Daily Mail",
  Cumnockchronicle: "Cumnock Chronicle",
  Gov: "GOV.UK",
  Parliament: "UK Parliament",
  "Uk News Yahoo": "Yahoo UK News",
  Theguardian: "The Guardian",
  Scottishdailyexpress: "Scottish Daily Express",
  Pressandjournal: "Press and Journal",
  "Johnogroat-journal": "John O'Groat Journal",
  Midlothianview: "Midlothian View",
  Thecourier: "The Courier",
  Dailyrecord: "Daily Record",
  Bordertelegraph: "Border Telegraph",
  Change: "Change.org",
  Rechargenews: "Recharge News",
  Thetimes: "The Times",
  Express: "Daily Express",
  Eastlothiancourier: "East Lothian Courier",
  "Inverness-courier": "Inverness Courier",
  "Northern-times": "Northern Times",
  Msn: "MSN",
  Theferret: "The Ferret",
  "Sealetters Substack": "Sea Letters (Substack)",
  Shetlandtimes: "Shetland Times",
  Scotcourts: "Scottish Courts",
};
function prettySource(name) {
  return PRETTY_SOURCE[name] || name;
}
function truncate(s, n) {
  return s.length <= n ? s : s.slice(0, n).replace(/\s+\S*$/, "") + "…";
}

// Distinguishes a formal planning objection from a community discussion post.
// A record is only ever labelled "Formal objection" when its source is an
// official planning-portal type (e.g. a future "planning_portal" source) --
// never inferred from wording, tone, or category. Every record currently in
// this dataset comes from a Facebook community group (source.type ===
// "facebook_group"), so today this always renders "Community discussion";
// the check exists so a future official-source record renders correctly
// without a code change here.
const OFFICIAL_SOURCE_TYPES = new Set(["planning_portal", "official_consultation"]);
function sourceVerification(record) {
  const type = record.source?.type;
  if (OFFICIAL_SOURCE_TYPES.has(type)) {
    return { label: "Formal objection", cls: "pd-verify--formal" };
  }
  return { label: "Community discussion", cls: "pd-verify--community" };
}
// A card's preview line: prefer the AI summary when one was generated, else
// fall back to the poster's own captured words (real archive content, just
// never previously shown on the card) -- only omitted when neither exists.
function cardExcerpt(r) {
  if (r.summary) return r.summary;
  if (r.bodyText) return truncate(r.bodyText.replace(/\s+/g, " ").trim(), 220);
  return "";
}

export function renderFeed(container, records, { selectedId, onSelect, mirrorIds }) {
  container.innerHTML = "";
  if (records.length === 0) {
    container.innerHTML = `<div class="pd-empty">No discussions match the current search and filters.<br>Try widening the date range or clearing a filter.</div>`;
    return;
  }

  let lastDate = null;
  for (const r of records) {
    if (r.date !== lastDate) {
      lastDate = r.date;
      const h = document.createElement("div");
      h.className = "pd-date-header";
      h.textContent = fmtHeader(r.date);
      container.appendChild(h);
    }

    const card = document.createElement("article");
    card.className = "pd-card" + (r.id === selectedId ? " is-selected" : "");
    card.dataset.id = r.id;
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Open discussion: ${r.title}`);
    const thumb = (r.photos && r.photos[0]) || r.previewImage;
    const verify = sourceVerification(r);
    card.innerHTML = `
      ${mirrorIds?.has(r.id) ? `<span class="pd-tag pd-tag--featured">&#9733; ${mirrorBadgeLabel(mirrorIds.size)}</span>` : ""}
      ${thumb ? `<img class="pd-card-thumb" src="${safeUrl(thumb)}" alt="" loading="lazy">` : ""}
      <h3 class="pd-card-title">${escapeHtml(r.title)}</h3>
      ${cardExcerpt(r) ? `<p class="pd-card-summary">${escapeHtml(cardExcerpt(r))}</p>` : ""}
      <div class="pd-card-meta">
        <span class="pd-verify ${verify.cls}">${verify.label}</span>
        ${(r.categories || []).map((c) => `<span class="pd-tag pd-tag--tech">${escapeHtml(c)}</span>`).join("")}
        ${(r.topics || []).slice(0, 3).map((t) => `<span class="pd-tag">${escapeHtml(t)}</span>`).join("")}
      </div>
      ${field("Location", r.location)}
      ${field("Project", r.project)}
      ${field("Developer", r.developer)}
      ${field("Council", r.council)}
      ${field("Authority", r.authority)}
      <div class="pd-card-source">Source: ${escapeHtml(r.source.label)}${r.mediaCount ? ` &middot; ${r.mediaCount} photo${r.mediaCount > 1 ? "s" : ""}` : ""}</div>
    `;
    card.addEventListener("click", () => onSelect(r.id));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onSelect(r.id);
      }
    });
    container.appendChild(card);
  }
}

export function scrollFeedTo(container, id) {
  const el = container.querySelector(`.pd-card[data-id="${CSS.escape(id)}"]`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

// The poster's own uploaded photo(s) always take priority; if there are none,
// fall back to the linked article's own preview image (still the source's own
// picture, not generated or guessed).
function detailPhotos(record) {
  if (record.photos && record.photos.length) {
    return `<div class="pd-detail-photos">${record.photos
      .map((p) => `<img src="${safeUrl(p)}" alt="Photo from the post">`)
      .join("")}</div>`;
  }
  if (record.previewImage) {
    return `<div class="pd-detail-photos"><img src="${safeUrl(record.previewImage)}" alt="Preview image from the linked article"></div>`;
  }
  return "";
}

// When the archive captured nothing to show (no body text, no summary, no
// mirror, no photo), fill the space with a clear, honest call to action
// instead of either a disclaimer paragraph or bare whitespace -- never
// invents content, just makes "go look on Facebook" the obvious, designed
// next step rather than something that reads as broken.
function detailTextNote(record, hasMirror) {
  if (record.bodyText || record.summary || hasMirror) return "";
  const hasPhoto = (record.photos && record.photos.length) || record.previewImage;
  if (hasPhoto) return ""; // a photo is already enough content on its own

  const context = record.externalSource
    ? `<p class="pd-detail-empty-context">Shared a link to an article from ${escapeHtml(prettySource(record.externalSource))}.</p>`
    : "";
  return `
    <div class="pd-detail-empty">
      ${context}
      <a class="pd-detail-empty-cta" href="${safeUrl(record.source.url)}" target="_blank" rel="noopener">View the original post on Facebook &#8599;</a>
    </div>`;
}

// A record only carries a Project field when the enrichment pipeline
// corroborated the match (see provenance.project.confidence in the data);
// this is never guessed here. Absence is shown explicitly rather than
// silently omitted, so a reader can tell "no project found" apart from
// "project field not checked yet".
function projectField(record) {
  if (record.project) return field("Project", record.project);
  return `<div class="pd-field pd-field--unverified"><span>Project</span> Not identified from this post</div>`;
}

export function renderDetail(panel, record, { onBack, hasMirror = false }) {
  const verify = sourceVerification(record);
  panel.innerHTML = `
    <button class="pd-back" type="button">&larr; Back to list</button>
    <article class="pd-detail">
      <div class="pd-detail-date">${fmtHeader(record.date)}</div>
      <h2>${escapeHtml(record.title)}</h2>
      <span class="pd-verify ${verify.cls}">${verify.label}</span>
      ${detailPhotos(record)}
      ${record.bodyText ? `<p class="pd-detail-body">${escapeHtml(record.bodyText)}</p>` : ""}
      ${record.summary ? `<p class="pd-detail-summary">${escapeHtml(record.summary)}</p>` : ""}
      ${detailTextNote(record, hasMirror)}
      <div class="pd-card-meta">
        ${(record.categories || []).map((c) => `<span class="pd-tag pd-tag--tech">${escapeHtml(c)}</span>`).join("")}
        ${(record.topics || []).map((t) => `<span class="pd-tag">${escapeHtml(t)}</span>`).join("")}
      </div>
      ${field("Location", record.location)}
      ${projectField(record)}
      ${field("Developer", record.developer)}
      ${field("Council", record.council)}
      ${field("Authority", record.authority)}
      ${field("Status", record.developmentStatus)}
      <div class="pd-detail-source">
        Source: ${escapeHtml(record.source.label)} &middot;
        <a href="${safeUrl(record.source.url)}" target="_blank" rel="noopener">View original post &#8599;</a>
      </div>
      ${
        (record.externalLinks || []).length
          ? `<div class="pd-detail-links">Referenced: ${record.externalLinks
              .map((u) => `<a href="${safeUrl(u)}" target="_blank" rel="noopener">${escapeHtml(hostOf(u))} &#8599;</a>`)
              .join(" · ")}</div>`
          : ""
      }
      <div id="pd-mirror-slot"></div>
    </article>`;
  panel.querySelector(".pd-back").addEventListener("click", onBack);
}

// Renders a curated original-post mirror (data/mirror/<id>.json -- see
// data/mirror/README.md) into the slot left by renderDetail above. Never
// called unless the site owner has explicitly published that record's
// mirror file -- either by hand (a screenshot) or via promote-to-mirror.mjs
// (U10-C), always a deliberate per-record decision either way.
const MIRROR_CONTACT_EMAIL = "slava@atlasglobal.energy";

// "Featured" is honest while mirrors are the hand-picked few the 2026-09-11
// decision scoped this to; past a rough threshold the same badge would
// misleadingly imply every post might get one. Recomputed from the
// manifest's actual size on every render (plan U10-D) so this can't
// silently go stale as coverage grows -- never a one-time copy edit.
const FEATURED_THRESHOLD = 15;
function mirrorBadgeLabel(totalMirrorCount) {
  return totalMirrorCount <= FEATURED_THRESHOLD ? "Featured original post" : "Original post available";
}

function provenanceLine(mirror) {
  const label =
    mirror.capturedMethod === "rescrape_pipeline"
      ? "Captured via an authorized archive re-scrape"
      : "Manually captured by the site owner from Facebook";
  return `${label}${mirror.capturedAt ? ` on ${escapeHtml(mirror.capturedAt)}` : ""} &mdash; published individually, never automatically or in bulk.`;
}

export function renderMirror(panel, mirror, { totalMirrorCount = 1 } = {}) {
  const slot = panel.querySelector("#pd-mirror-slot");
  if (!slot) return; // panel has moved on (user navigated back) -- drop it
  const photos = (mirror.photos || [])
    .map((p) => `<img src="${escapeHtml(p)}" alt="Photo from the original Facebook post" loading="lazy">`)
    .join("");
  const comments = (mirror.comments || [])
    .map(
      (c) => `<div class="pd-mirror-comment">
        <div class="pd-mirror-comment-author">${escapeHtml(c.author)}</div>
        <div class="pd-mirror-comment-text">${escapeHtml(c.text)}</div>
        ${c.timestampLabel ? `<div class="pd-mirror-comment-time">${escapeHtml(c.timestampLabel)}</div>` : ""}
      </div>`
    )
    .join("");
  slot.innerHTML = `
    <section class="pd-mirror">
      <span class="pd-tag pd-tag--featured">&#9733; ${mirrorBadgeLabel(totalMirrorCount)}</span>
      <h4 class="pd-mirror-heading">Original Facebook post</h4>
      ${mirror.postText ? `<p class="pd-mirror-text">${escapeHtml(mirror.postText)}</p>` : ""}
      ${photos ? `<div class="pd-mirror-photos">${photos}</div>` : ""}
      ${comments ? `<div class="pd-mirror-comments">${comments}</div>` : ""}
      ${
        comments
          ? `<p class="pd-mirror-removal">Commenter named above and want this removed? Contact <a href="mailto:${MIRROR_CONTACT_EMAIL}">${MIRROR_CONTACT_EMAIL}</a>.</p>`
          : ""
      }
      <p class="pd-mirror-provenance">${provenanceLine(mirror)}</p>
    </section>`;
}
