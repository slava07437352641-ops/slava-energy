// MapLibre GL map controller: parchment base, clustered discussion markers,
// marker<->card sync, smart auto-fit, "Fit results" (spec §11-§13).
// Relies on window.maplibregl (vendored UMD build).

import { PARCHMENT_STYLE } from "./parchment-style.js?v=20260913d";

const SCOTLAND_BOUNDS = [
  [-8.9, 54.5],
  [0.5, 61.1],
];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export class DiscussionMap {
  constructor(el, { onSelect, onClusterOpen }) {
    this.onSelect = onSelect;
    this.onClusterOpen = onClusterOpen;
    this.userMovedView = false;
    this.map = new maplibregl.Map({
      container: el,
      style: PARCHMENT_STYLE,
      bounds: SCOTLAND_BOUNDS,
      fitBoundsOptions: { padding: 40 },
      attributionControl: {
        compact: true,
        customAttribution: "Turbines: windfarmdata.co.uk / DESNZ REPD (OGL v3.0) · Grid: © OpenInfraMap, © OpenStreetMap contributors",
      },
      maxZoom: 15,
      minZoom: 4,
    });
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    this.map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    this.map.on("dragstart", () => (this.userMovedView = true));
    this.map.on("zoomstart", (e) => {
      if (e.originalEvent) this.userMovedView = true;
    });

    this.ready = new Promise((res) => this.map.on("load", () => {
      this._initLayers();
      res();
    }));

    this._infraLoaded = {};
  }

  _initLayers() {
    this.map.addSource("discussions", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      cluster: true,
      clusterRadius: 46,
      clusterMaxZoom: 12,
    });

    this.map.addLayer({
      id: "clusters",
      type: "circle",
      source: "discussions",
      filter: ["has", "point_count"],
      paint: {
        "circle-color": "#b9502f",
        "circle-opacity": 0.85,
        "circle-stroke-color": "#f3ecda",
        "circle-stroke-width": 2,
        "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 40, 24],
      },
    });
    this.map.addLayer({
      id: "cluster-count",
      type: "symbol",
      source: "discussions",
      filter: ["has", "point_count"],
      layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": ["Noto Sans Regular"], "text-size": 12 },
      paint: { "text-color": "#f3ecda" },
    });
    this.map.addLayer({
      id: "point",
      type: "circle",
      source: "discussions",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": ["case", ["boolean", ["feature-state", "selected"], false], "#7a354a", "#c07018"],
        "circle-radius": ["case", ["boolean", ["feature-state", "selected"], false], 9, 6],
        "circle-stroke-color": "#f3ecda",
        "circle-stroke-width": 2,
      },
    });

    this.map.on("click", "clusters", async (e) => {
      const f = this.map.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0];
      const source = this.map.getSource("discussions");
      const clusterId = f.properties.cluster_id;
      const currentZoom = this.map.getZoom();
      let expansionZoom;
      try {
        expansionZoom = await source.getClusterExpansionZoom(clusterId);
      } catch {
        expansionZoom = null;
      }
      // Some records share the exact same coordinate (e.g. several posts all
      // geocoded to the same town centre) -- there is no zoom level at which
      // identical points visually separate, so the usual "zoom in to expand"
      // never resolves anything and a click effectively does nothing useful.
      // When expanding would not meaningfully change the view, list the
      // cluster's own posts instead so they can be picked directly.
      if (!Number.isFinite(expansionZoom) || expansionZoom <= currentZoom + 0.1) {
        const leaves = await source.getClusterLeaves(clusterId, f.properties.point_count, 0);
        this.onClusterOpen?.(leaves.map((l) => l.properties));
        return;
      }
      this.userMovedView = true;
      this.map.easeTo({ center: f.geometry.coordinates, zoom: expansionZoom });
    });
    this.map.on("click", "point", (e) => {
      // Above clusterMaxZoom, coincident points (several posts geocoded to the
      // same town centre) render as separate, fully-overlapping "point"
      // features rather than a cluster bubble -- e.features[0] would silently
      // pick whichever one happens to be on top. Check for siblings at the
      // same pixel first.
      const hits = this.map.queryRenderedFeatures(e.point, { layers: ["point"] });
      const uniqueIds = [...new Map(hits.map((h) => [h.properties.id, h])).values()];
      if (uniqueIds.length > 1) {
        this.onClusterOpen?.(uniqueIds.map((h) => h.properties));
        return;
      }
      const id = e.features[0].properties.id;
      this.onSelect(id, { fromMap: true });
      this._popup(e.features[0]);
    });
    for (const l of ["clusters", "point"]) {
      this.map.on("mouseenter", l, () => (this.map.getCanvas().style.cursor = "pointer"));
      this.map.on("mouseleave", l, () => (this.map.getCanvas().style.cursor = ""));
    }
  }

  // ---- Infrastructure layers (turbines / substations / power lines) ----
  // Data: OpenInfraMap-derived local exports, converted by
  // build-discussions/build-infra-layers.mjs. Off by default; fetched once,
  // the first time each layer is toggled on.
  static INFRA_LAYERS = {
    turbines: { url: "data/infra/turbines.geojson", kind: "point" },
    substations: { url: "data/infra/substations.geojson", kind: "point" },
    powerLines: { url: "data/infra/power-lines.geojson", kind: "line" },
  };

  async setInfraLayerVisible(name, visible) {
    await this.ready;
    const cfg = DiscussionMap.INFRA_LAYERS[name];
    if (!cfg) return;
    if (!this._infraLoaded[name]) {
      this._infraLoaded[name] = true;
      let data = { type: "FeatureCollection", features: [] };
      try {
        const res = await fetch(cfg.url, { cache: "force-cache" });
        if (res.ok) data = await res.json();
      } catch {
        // no infra data available -- layer just stays empty, never invented
      }
      const sourceId = `infra-${name}`;
      this.map.addSource(sourceId, { type: "geojson", data });
      if (cfg.kind === "point") {
        this.map.addLayer({
          id: `${sourceId}-point`,
          type: "circle",
          source: sourceId,
          paint: {
            "circle-color": name === "turbines" ? "#4e7c59" : "#3b6e8f",
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 3.5, 8, 4.5, 12, 6, 16, 9],
            "circle-stroke-color": "#f3ecda",
            "circle-stroke-width": 1,
            "circle-opacity": 0.9,
          },
        });
        this.map.on("click", `${sourceId}-point`, (e) => this._infraPopup(e.features[0], name, e.lngLat));
      } else {
        this.map.addLayer({
          id: `${sourceId}-line`,
          type: "line",
          source: sourceId,
          paint: {
            "line-color": [
              "step",
              ["coalesce", ["get", "voltageKv"], 0],
              "#c07018",
              132,
              "#7a354a",
              275,
              "#b9502f",
            ],
            "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1.4, 8, 1.8, 12, 2.6, 16, 4.5],
            "line-opacity": 0.85,
          },
        });
        this.map.on("click", `${sourceId}-line`, (e) => this._infraPopup(e.features[0], name, e.lngLat));
      }
      for (const l of [`${sourceId}-point`, `${sourceId}-line`]) {
        this.map.on("mouseenter", l, () => (this.map.getCanvas().style.cursor = "pointer"));
        this.map.on("mouseleave", l, () => (this.map.getCanvas().style.cursor = ""));
      }
    }
    const layerId = cfg.kind === "point" ? `infra-${name}-point` : `infra-${name}-line`;
    if (this.map.getLayer(layerId)) {
      this.map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
    }
  }

  _infraPopup(feature, name, lngLat) {
    const p = feature.properties;
    const LABELS = { turbines: "Wind turbine", substations: "Substation", powerLines: "Power line" };
    const lines = [`<div class="pd-pop-title">${esc(p.name || LABELS[name])}</div>`];
    if (p.operator) lines.push(`<div class="pd-pop-loc">${esc(p.operator)}</div>`);
    if (p.voltageKv) lines.push(`<div class="pd-pop-cat">${esc(p.voltageKv)} kV</div>`);
    if (p.rating) lines.push(`<div class="pd-pop-cat">${esc(p.rating)}${p.turbineCount ? ` · ${esc(p.turbineCount)} turbine${p.turbineCount === 1 ? "" : "s"}` : ""}</div>`);
    if (p.status) lines.push(`<div class="pd-pop-loc">${esc(p.status)}</div>`);
    const at = lngLat || (feature.geometry.type === "Point" ? feature.geometry.coordinates : null);
    if (!at) return;
    new maplibregl.Popup({ offset: 8, closeButton: false, className: "pd-popup" })
      .setLngLat(at)
      .setHTML(lines.join(""))
      .addTo(this.map);
  }

  _popup(feature) {
    const p = feature.properties;
    const cat = p.category ? `<div class="pd-pop-cat">${esc(p.category)}</div>` : "";
    const loc = p.location ? `<div class="pd-pop-loc">${esc(p.location)}</div>` : "";
    new maplibregl.Popup({ offset: 12, closeButton: false, className: "pd-popup" })
      .setLngLat(feature.geometry.coordinates)
      .setHTML(
        `<div class="pd-pop-date">${esc(p.dateLabel)}</div><div class="pd-pop-title">${esc(p.title)}</div>${cat}${loc}` +
          `<button class="pd-pop-open" data-id="${esc(p.id)}" type="button">View discussion &rarr;</button>`
      )
      .addTo(this.map);
    setTimeout(() => {
      document.querySelector(".pd-pop-open")?.addEventListener("click", (ev) => this.onSelect(ev.target.dataset.id));
    }, 0);
  }

  setData(records) {
    const features = records
      .filter((r) => r.coordinates && Number.isFinite(r.coordinates.lat) && Number.isFinite(r.coordinates.lon))
      .map((r) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [r.coordinates.lon, r.coordinates.lat] },
        properties: {
          id: r.id,
          title: r.title,
          dateLabel: new Date(r.date + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }),
          category: (r.categories || [])[0] || "",
          location: r.location || "",
        },
      }));
    this._features = features;
    this.ready.then(() => this.map.getSource("discussions")?.setData({ type: "FeatureCollection", features }));
  }

  autoFit() {
    this.ready.then(() => {
      if (this.userMovedView || !this._features?.length) return;
      const b = new maplibregl.LngLatBounds();
      this._features.forEach((f) => b.extend(f.geometry.coordinates));
      this.map.fitBounds(b, { padding: 60, maxZoom: 11, duration: 500 });
    });
  }

  fitResults() {
    this.userMovedView = false;
    if (!this._features?.length) {
      this.map.fitBounds(SCOTLAND_BOUNDS, { padding: 40 });
      return;
    }
    this.autoFit();
  }

  select(id) {
    this.ready.then(() => {
      if (this._selected) this.map.setFeatureState({ source: "discussions", id: this._selected }, { selected: false });
      // geojson features need promoteId to use setFeatureState by property; fall
      // back to a simple visual re-render via filter for the pilot.
      this._selected = id;
    });
  }

  getView() {
    const c = this.map.getCenter();
    return { lat: c.lat, lon: c.lng, zoom: this.map.getZoom() };
  }
  onMoveEnd(cb) {
    this.map.on("moveend", () => cb(this.getView()));
  }
}
