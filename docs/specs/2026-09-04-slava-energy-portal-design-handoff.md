# Developer Design Handoff Spec: Slava.Energy Executive Intelligence Portal

**Document Version:** 1.0.0  
**Date:** 2026-09-04  
**Design System:** Apple Human Interface Guidelines (HIG) + KRE Brand Standards  
**Target Domain:** [slava.energy](https://slava.energy)  
**Local Preview:** [http://localhost:8089/index.html](http://localhost:8089/index.html)  

---

## 1. Executive Overview
The **Slava.Energy Executive Intelligence Portal** is a high-performance, single-page intelligence interface delivering due diligence on 14,657 trackable clean energy projects (398.2 GW) across the United Kingdom.

The interface adheres strictly to Apple Human Interface Guidelines (SF Pro typography, translucent frosted-glass materials, tactile segmented controls, and asymmetric bento grids) while integrating Koehler Renewable Energy (KRE) green branding (`#007D3F`).

---

## 2. Layout & Grid Architecture

- **Max Content Container:** `1440px` centered with auto margins.
- **Horizontal Viewport Padding:**
  - Desktop (>1024px): `2rem` (32px)
  - Tablet (768px–1024px): `1.5rem` (24px)
  - Mobile (<768px): `1.25rem` (20px)
  - Small Mobile (<480px): `1rem` (16px)

### Bento KPI Grid System
To prevent ragged wrapping, the 5 executive KPI metric cards use a structured responsive grid:
- **Desktop (≥ 1200px):** 5-column rigid grid (`repeat(5, 1fr)`). All 5 cards span a single balanced row.
- **Tablet / Medium Desktop (768px – 1199px):** 6-column bento grid (`repeat(6, 1fr)`):
  - Row 1: Cards 1, 2, 3 each span 2 columns (`grid-column: span 2`).
  - Row 2: Cards 4, 5 each span 3 columns (`grid-column: span 3`).
- **Mobile (480px – 767px):** 2-column grid (`repeat(2, 1fr)`):
  - Cards 1–4 span 1 column each.
  - Card 5 spans 2 columns (`grid-column: span 2`).
- **Small Mobile (< 480px):** Single column stack (`repeat(1, 1fr)`).

---

## 3. Design Tokens

### Color Palette
| Token | HEX / RGBA | Role / Usage |
|---|---|---|
| `--brand-green` | `#007D3F` | KRE Primary Brand Accent, active indicators, status dots |
| `--brand-green-light` | `#009A4E` | Hover state for primary buttons |
| `--brand-green-subtle` | `rgba(0, 125, 63, 0.08)` | Chip background, focus glow |
| `--system-bg` | `#F5F5F7` | Apple system warm grey page canvas |
| `--card-solid` | `#FFFFFF` | Solid opaque card surface |
| `--nav-glass-bg` | `rgba(255, 255, 255, 0.85)` | Glass header fill (paired with `backdrop-filter: blur(20px)`) |
| `--label-primary` | `#1D1D1F` | Headlines, primary KPI numbers, bold emphasis |
| `--label-secondary` | `#6E6E73` | Subheads, section captions, metadata |
| `--label-tertiary` | `#86868B` | Footers, disabled states, subtle microcopy |
| `--separator-opaque` | `#E5E5EA` | Card borders, table dividers, header stroke |
| `--accent-gold` | `#D97706` | Grid queue / Awaiting Construction indicator |
| `--accent-teal` | `#0D9488` | Active Construction indicator |
| `--accent-blue` | `#2563EB` | Statutory Planning Review indicator |

### Typography
| Token | Font Family | Size | Weight | Tracking / Line Height |
|---|---|---|---|---|
| `font-headline-hero` | SF Pro Display, -apple-system | `2.75rem` (44px) | 700 (Bold) | `-0.035em` / 1.12 |
| `font-title-surface` | SF Pro Display, -apple-system | `1.45rem` (23px) | 700 (Bold) | `-0.02em` / 1.2 |
| `font-body-lead` | SF Pro Text, -apple-system | `1.15rem` (18px) | 400 (Regular) | `-0.015em` / 1.5 |
| `font-kpi-num` | SF Mono, Menlo, monospace | `2.0rem` (32px) | 700 (Bold) | `-0.03em` / 1.1 |
| `font-kpi-unit` | SF Pro Display, -apple-system | `1.1rem` (17px) | 600 (Semibold) | `-0.02em` |
| `font-control` | SF Pro Text, -apple-system | `0.85rem` (13.5px) | 500 (Medium) | Normal |
| `font-eyebrow` | SF Pro Text, -apple-system | `0.8rem` (12px) | 600 (Semibold) | `0.06em` (Uppercase) |

### Surface Radii & Shadows
- **Card Radius:** `20px` (`border-radius: 20px`)
- **Bento Tile Radius:** `18px` (`border-radius: 18px`)
- **Interactive Pill:** `980px` (`border-radius: 980px`)
- **Control Radius:** `8px` (`border-radius: 8px`)
- **Subtle Elevation:** `box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04)`
- **Hover Elevation:** `box-shadow: 0 12px 30px rgba(0, 0, 0, 0.08)`

---

## 4. Components & Interactive States

### 1. Navigation Header
- **Container:** Sticky glass bar (`position: sticky; top: 0; z-index: 1000; backdrop-filter: blur(20px)`).
- **Brand Avatar:** 36x36px rounded square (`border-radius: 9px`), `#007D3F` with white bolt icon.
- **Brand Label:** `slava.energy` (1.15rem / semibold 600) with subtitle `UK Renewable Intelligence`.
- **Status Pill:** Real-time sync badge `DESNZ REPD Q2 2026` with 7px pulsing green dot. Hides on mobile (<640px) to prevent wrapping.
- **CTA Button:** `Contact & Advisory` pill button (`background: #007D3F; color: #FFF; border-radius: 980px`). Scales up `1.02x` on hover.

### 2. Bento KPI Grid (Option 1 Metrics)
- **Top Accent Line:** 4px high colored accent bar on each card:
  - Card 1 (Total Pipeline): `#007D3F`
  - Card 2 (Awaiting Construction / Grid Queue): `#D97706` (Amber/Gold)
  - Card 3 (Operational Realised Assets): `#007D3F`
  - Card 4 (Under Active Construction): `#0D9488` (Teal)
  - Card 5 (Live in Planning Review): `#2563EB` (Blue)
- **Hover Effect:** `transform: translateY(-2px); box-shadow: 0 12px 30px rgba(0, 0, 0, 0.08); transition: transform 0.2s ease`.

### 3. Native Filter Bar
- **Segmented Control:** Apple iOS segmented pill (`background: rgba(118, 118, 128, 0.12); border-radius: 8px; padding: 2px`).
  - Active button: `#FFFFFF`, `box-shadow: 0 2px 5px rgba(0,0,0,0.1)`.
  - Inactive button: Transparent, text `#1D1D1F`.
- **Dropdown Filters:** Clean white select cards with 8px radius, `#E5E5EA` border.
  - Country: `All UK Jurisdictions`, `Scotland Only`, `England Only`, `Wales Only`, `Northern Ireland Only`.
  - Technology: `All Technologies`, `Battery Storage (BESS)`, `Solar PV`, `Wind Onshore`, `Wind Offshore`.
- **Live Counter:** Monospaced active throughput counter (e.g. `14,657 projects • 398.2 GW active flow`).

### 4. Sankey Canvas & High-Res PNG Export
- **Engine:** Plotly.js WebGL/SVG Sankey diagram with custom node padding (`18px`) and thickness (`22px`).
- **Export Trigger:** Native button `Export High-Res PNG` invoking `Plotly.downloadImage` at 2x scale (2880x1600) with date-stamped filename: `slava_energy_macro_planning_lifecycle_YYYY-MM-DD.png`.

### 5. WebGIS Discovery Banner
- **Gradient Background:** `linear-gradient(135deg, #064E3B 0%, #0F172A 100%)`.
- **Call-to-Action:** White pill button leading to `scotland_council_renewable_objections_map.html`.

---

## 5. Responsive Behavior Matrix

| Viewport Width | KPI Bento Grid | Navigation Bar | Hero Typography | Filter Bar | Sankey Canvas Height |
|---|---|---|---|---|---|
| **≥ 1200px** (Desktop Wide) | 5 cols (1 row) | Full pills + CTA | 2.75rem | Inline cluster | 750px |
| **768px – 1199px** (Tablet) | 6 cols (3 top, 2 bottom) | Full pills + CTA | 2.5rem | Inline cluster | 680px |
| **480px – 767px** (Mobile) | 2 cols (2 top, 2 mid, 1 full bottom) | Brand + CTA (pill hidden) | 2.0rem | Stacked wrap | 580px |
| **< 480px** (Small Mobile) | 1 col (stacked vertical) | Brand + CTA | 1.65rem | Full-width controls | 500px |

---

## 6. Accessibility & Performance Specs
- **Contrast Ratio:** All body text (`#1D1D1F` and `#6E6E73`) achieves WCAG 2.1 AA standard on `#FFFFFF` and `#F5F5F7` canvases (>4.5:1).
- **Keyboard Navigation:** Native `<button>` and `<select>` elements retain standard macOS focus rings (`outline: 2px solid var(--brand-green)`).
- **Tabular Figures:** Numbers formatted with `font-variant-numeric: tabular-nums` via `SF Mono` for jitter-free live filtering updates.
- **Rendering Performance:** 60fps interaction during dropdown selection and metric toggling.

---

## 7. Deployment & Verification
- **Target Repository:** `slava07437352641-ops/slava-energy`
- **DNS / Custom Domain:** `slava.energy` → GitHub Pages (DNS A records: `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`).
