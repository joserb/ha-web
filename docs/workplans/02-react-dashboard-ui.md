---
status: in-progress
created: 2026-07-26
updated: 2026-07-26
---

# React dashboard UI and sensor visualizations

## Objective

Replace the prototype static frontend with an English-only React application that presents the current `zro-pi` sensor inventory through accessible, responsive and theme-aware visualizations.

The implementation will use React 19, TypeScript, Vite, Tailwind CSS v4 and shadcn/ui. Recharts will provide trend charts, following the proven interaction and data-display patterns in `zro-dashboard` while updating its React 18/Tailwind 3 foundation.

## Product language

- All visible interface text must be English.
- Dates, times and numbers use the browser locale, while labels remain English.
- API field names and MQTT topics are not translated.
- Empty, loading, stale, disconnected and error states must all have explicit English copy.
- Tests should query stable accessible names rather than translated implementation details.

## Technology decisions

- React 19 with TypeScript and strict type checking.
- Vite as development server and production builder.
- Tailwind CSS v4 using CSS-first theme configuration.
- shadcn/ui components copied into the repository and owned by the project.
- Recharts for trend charts and timeline axes.
- Lucide React for interface icons.
- Native `fetch` initially; introduce a query library only if caching complexity justifies it.
- Build assets into an immutable `dist/` image served by Nginx. Do not mount source files into the production web server.
- Keep the current static frontend available until the React build passes end-to-end verification.

## Information architecture

### Header

- Product name and live/disconnected indicator.
- Global time-range selector with `1h`, `6h`, `12h`, `1d`, `7d`, `30d`, `3m`, `6m`, `1y` and `forever`.
- Theme selector with `System`, `Light` and `Dark`.
- Compact responsive layout on small screens.

### Current conditions

- Temperature is the only metric displayed as a `meter` card.
- Door and vibration devices use event timeline cards.
- Humidity, pressure and battery values are displayed in trend cards, not standalone meters.
- Stale values show their source timestamp and a visible stale state.

### Trends

- Stacked chart cards grouped by compatible family/unit.
- Initial families: temperatures, humidities, pressures and batteries.
- Every family and individual channel can be enabled or disabled.
- Channel choices persist locally.
- All charts share the global time range.
- Tooltips and legends follow the `zro-dashboard` `TimeSeriesChart` pattern.
- Incompatible units never share a misleading Y axis.

## Theme behavior

- Default preference is `System`.
- `System` follows `prefers-color-scheme` and reacts to operating-system changes without reload.
- Explicit `Light` or `Dark` preferences override the system and persist in `localStorage`.
- An inline bootstrap script applies the resolved theme before React loads to prevent a flash of the wrong theme.
- shadcn semantic tokens define background, foreground, card, muted, border, destructive and chart colors.
- Recharts axes, grids, legends and tooltips consume the same semantic theme.
- Both themes must meet WCAG AA contrast for body text and controls.

## Temperature meter card

The visual reference is the supplied semicircular gauge: prominent current value and unit inside the arc, location and metric label above, and a compact historical context below.

### Zones

Default domestic temperature zones are configurable per sensor but start with:

| Range | Meaning | Color direction |
|---|---|---|
| below 10 °C | very cold | darkest blue |
| 10–16 °C | cold | medium blue |
| 16–20 °C | cool | light blue |
| 20–23 °C | comfortable | green |
| 23–26 °C | warm | yellow |
| 26–30 °C | hot | orange |
| above 30 °C | very hot | red |

- The scale must not imply that ordinary domestic values span 0–100; default temperature domain is configurable and initially `-5..45 °C`.
- The current value, unit, last-update age and stale state remain readable without interpreting color.
- The needle and arc are SVG/React, responsive and keyboard-independent; do not use a raster gauge.
- Reduced-motion preferences disable needle animation.
- Each temperature card includes a small trend plot for the selected global range.

## Event timeline cards

Door opening and vibration activity use interval timelines rather than numeric charts.

### Visual model

- Horizontal time axis covering the selected global range.
- Muted gray/translucent baseline represents no event.
- Green rectangles represent active intervals:
  - Door: open → closed.
  - Vibration: active → clear.
- An interval still active at the end of the range continues to `now` and receives an `Active now` label.
- Hover/focus tooltip shows start, end and duration.
- Summary shows current state, event count, total active duration and longest interval.
- Multiple rows may be used when several door or vibration channels exist.
- Small screens allow horizontal detail without making the whole page overflow.

### Interval semantics

- Backend returns normalized intervals; React does not pair raw events independently.
- Duplicate consecutive states are collapsed.
- A closing/clear event without a visible opening/active event starts at the range boundary only when state-before-range proves it was active.
- An opening/active event without a closing/clear event ends at `now`.
- Timestamps are stored and transmitted in UTC and rendered in the browser timezone.
- Door and vibration state mappings come from the `zro-pi` normalized contract.

## API work required

- Batch trend endpoint accepting validated sensor IDs and one closed-set range identifier.
- Response grouped by family/channel with timestamps aligned where practical.
- Interval endpoint for door and vibration channels.
- Query the state immediately before the selected range to construct boundary intervals correctly.
- Preserve the existing single-sensor history/events endpoints during migration.
- Return catalog metadata needed by meters: domain, zones, unit and stale threshold.
- Bound point counts and aggregation windows for every range, including `forever`.

## Component structure

```text
src/
├── app/
│   ├── App.tsx
│   └── providers.tsx
├── components/
│   ├── dashboard-header.tsx
│   ├── global-range-select.tsx
│   ├── theme-select.tsx
│   ├── temperature-meter-card.tsx
│   ├── trend-card.tsx
│   ├── channel-selector.tsx
│   ├── event-timeline-card.tsx
│   └── sensor-state.tsx
├── components/ui/          # shadcn/ui-owned components
├── hooks/
│   ├── use-dashboard-data.ts
│   ├── use-live-sensors.ts
│   ├── use-preferences.ts
│   └── use-theme.ts
├── lib/
│   ├── api.ts
│   ├── ranges.ts
│   ├── temperature-zones.ts
│   └── utils.ts
└── types/
    └── sensors.ts
```

## Delivery phases

### Phase 1 — React foundation

- [x] Create the React 19 + TypeScript + Vite application.
- [x] Configure Tailwind CSS v4 and shadcn/ui aliases/tokens.
- [ ] Add lint, type-check, unit-test and production-build commands.
- [x] Build a multi-stage frontend image and update Compose/Nginx.
- [ ] Preserve a simple rollback to the existing static frontend.

### Phase 2 — Shell, language and themes

- [x] Implement the responsive dashboard shell using shadcn/ui.
- [x] Move every visible string to English.
- [x] Implement `System`, `Light` and `Dark` without initial theme flash.
- [x] Implement the global time-range selector and preference persistence.
- [ ] Add loading, empty, error, disconnected and stale states.

### Phase 3 — Data contracts and trends

- [ ] Add the batch trend API and typed frontend client.
- [x] Port the useful Recharts conventions from `zro-dashboard`.
- [ ] Implement stacked trend cards by compatible family.
- [ ] Implement family and channel selectors with persisted choices.
- [ ] Verify all ten time ranges and bounded point counts.

### Phase 4 — Temperature meters

- [ ] Add configurable temperature domains and zones to catalog metadata.
- [x] Implement the responsive SVG semicircular meter.
- [x] Apply cold-blue, comfort-green and heat-yellow/orange/red zones.
- [ ] Add current value, unit, freshness and compact trend.
- [ ] Verify boundary values and reduced-motion behavior.

### Phase 5 — Door and vibration timelines

- [x] Normalize vibration into the dashboard catalog.
- [ ] Implement backend interval construction and boundary-state queries.
- [x] Implement the reusable event timeline card.
- [x] Use green active intervals and muted no-event background.
- [ ] Add summaries and accessible tooltip/focus behavior.
- [ ] Verify duplicate, incomplete and ongoing intervals.

### Phase 6 — Cutover and verification

- [ ] Add component and API contract tests.
- [ ] Test responsive layouts at mobile, tablet and desktop widths.
- [ ] Test both explicit themes and live system-theme changes.
- [ ] Validate against current `zro-pi` retained data and historical Home Assistant data.
- [x] Deploy through Tailscale and run smoke/end-to-end checks.
- [ ] Remove the prototype frontend only after rollback verification.

## Acceptance criteria

- The complete visible interface is English.
- Production uses React 19, Vite, Tailwind CSS v4 and shadcn/ui.
- Theme defaults to the user's system and supports persistent manual overrides.
- Temperature is the only metric represented by meter cards.
- Temperature meters use the requested cold/comfort/hot color progression.
- Humidity, pressure and battery channels appear in stacked trend cards.
- Families and individual channels can be disabled and remain disabled after reload.
- Door and vibration timelines use green active rectangles over a muted baseline.
- Timeline intervals and summaries are correct at range boundaries and for ongoing events.
- All visualizations respond to the single global range selector.
- Current `zro-pi` data and the historical Home Assistant series remain available.
- No frontend source mount or stale-module cache can break a production deployment.

## Risks and open decisions

- shadcn/ui does not provide a gauge or interval timeline; these will be owned project components built with SVG/Recharts primitives and shadcn containers/tooltips.
- The exact temperature domain and zone boundaries may need adjustment after observing seasonal domestic values; catalog configuration keeps them changeable.
- Very long ranges require retention/downsampling decisions before `forever` can guarantee useful resolution.
- `zro-dashboard` can provide interaction patterns, but its React 18/Tailwind 3 implementation must not be copied as build configuration.

## Progress log

- 2026-07-26: plan designed from the supplied gauge/timeline reference and review of `zro-dashboard` trend components.
- 2026-07-26: execution started with an isolated React 19/Vite/Tailwind v4 foundation so the current static dashboard remains available during migration.
- 2026-07-26: foundation typecheck and production build pass with zero reported npm vulnerabilities; responsive shell, global range and three-way theme preference are implemented.
- 2026-07-26: live catalog integration, four temperature gauges and Recharts family trends for humidity, pressure and battery pass typecheck and production build.
- 2026-07-26: door and vibration interval API plus reusable green-on-muted timeline card implemented for the first end-to-end timeline slice.
- 2026-07-26: React image deployed on `charo-vps`; 17 live channels, temperature meters, family trends and both timeline types pass production smoke checks.
