// A compact hand-authored MapLibre GL style: OpenFreeMap vector tiles
// (free, no API key) rendered in a warm sepia / antique-cartography palette
// to match the slava.it.com vintage parchment design.
//
// If the site later moves to a host that enforces the _headers CSP, add
//   connect-src https://tiles.openfreemap.org ;
//   img-src https://tiles.openfreemap.org data: ;
// (glyphs/sprite are served from the same host).

const OFM = "https://tiles.openfreemap.org";

export const PARCHMENT_STYLE = {
  version: 8,
  name: "Slava vintage parchment",
  glyphs: `${OFM}/fonts/{fontstack}/{range}.pbf`,
  sources: {
    ofm: {
      type: "vector",
      url: `${OFM}/planet`,
      attribution:
        '&copy; <a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> &middot; &copy; OpenStreetMap contributors',
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#efe6d2" } },

    {
      id: "water",
      type: "fill",
      source: "ofm",
      "source-layer": "water",
      paint: { "fill-color": "#cdd8d2", "fill-outline-color": "#b7c4bd" },
    },
    {
      id: "landcover-wood",
      type: "fill",
      source: "ofm",
      "source-layer": "landcover",
      filter: ["==", ["get", "class"], "wood"],
      paint: { "fill-color": "#e4ddc4", "fill-opacity": 0.55 },
    },
    {
      id: "landuse-residential",
      type: "fill",
      source: "ofm",
      "source-layer": "landuse",
      filter: ["==", ["get", "class"], "residential"],
      paint: { "fill-color": "#e9dfca", "fill-opacity": 0.4 },
    },

    {
      id: "boundary-admin",
      type: "line",
      source: "ofm",
      "source-layer": "boundary",
      filter: ["all", ["<=", ["get", "admin_level"], 4], [">=", ["get", "admin_level"], 2]],
      paint: {
        "line-color": "#9a7f5f",
        "line-dasharray": [3, 2],
        "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.5, 8, 1.4],
        "line-opacity": 0.6,
      },
    },
    {
      id: "boundary-admin-minor",
      type: "line",
      source: "ofm",
      "source-layer": "boundary",
      filter: [">", ["get", "admin_level"], 4],
      paint: { "line-color": "#b39a78", "line-dasharray": [1.5, 1.5], "line-width": 0.6, "line-opacity": 0.45 },
    },

    {
      id: "roads-major",
      type: "line",
      source: "ofm",
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk", "primary"]]],
      paint: {
        "line-color": "#c9a678",
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.4, 12, 2.2],
        "line-opacity": 0.7,
      },
    },
    {
      id: "roads-minor",
      type: "line",
      source: "ofm",
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["secondary", "tertiary", "minor"]]],
      minzoom: 9,
      paint: { "line-color": "#d3b891", "line-width": 0.7, "line-opacity": 0.5 },
    },

    {
      id: "place-labels",
      type: "symbol",
      source: "ofm",
      "source-layer": "place",
      filter: ["in", ["get", "class"], ["literal", ["city", "town", "village", "state"]]],
      layout: {
        "text-field": ["get", "name"],
        "text-font": ["Noto Sans Regular"],
        "text-size": ["interpolate", ["linear"], ["zoom"], 4, 10, 10, 15],
        "text-transform": "none",
        "text-letter-spacing": 0.04,
        "text-max-width": 7,
      },
      paint: {
        "text-color": "#5b4636",
        "text-halo-color": "#f3ecda",
        "text-halo-width": 1.6,
      },
    },
  ],
};
