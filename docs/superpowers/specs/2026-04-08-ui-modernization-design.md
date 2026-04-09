# TenderFlow UI Modernization — Design Spec
**Date:** 2026-04-08
**Demo deadline:** 2026-04-09 14:00

## Summary

Full UI overhaul of the React frontend using a **Precision Dark** aesthetic (Linear/Vercel energy). Pure CSS implementation — no new dependencies. Goal: seamless, animated, clutter-free UI with frontier-level tool call visualization for the ISTARI/Q-Hack demo.

---

## 1. Design System Additions (`index.css`)

New CSS custom properties:

```css
--ease-out-expo:  cubic-bezier(0.16, 1, 0.3, 1);
--ease-spring:    cubic-bezier(0.34, 1.56, 0.64, 1);
--ease-in-out:    cubic-bezier(0.4, 0, 0.2, 1);
--dur-fast:       120ms;
--dur-base:       220ms;
--dur-slow:       380ms;
--glow-accent:    0 0 0 3px rgba(99,102,241,0.18);
--surface-raised: #161616;
```

New global keyframes:
- `slideInUp` — `opacity: 0; translateY(14px)` → normal. Used by all entering cards/messages.
- `slideInLeft` — `opacity: 0; translateX(-12px)` → normal. Used by sidebar expansion.
- `expandDown` — `max-height: 0; opacity: 0` → `max-height: var; opacity: 1`. Used by collapsible panels.
- `shimmer` — gradient sweep left→right. Used by skeleton/loading states.
- `glowPulse` — box-shadow intensity oscillation. Used by active job dot.
- `dotTrail` — staggered scale+opacity. Used by `•••` status indicators.
- `spinRing` — `rotate(0→360deg)`. Used by tool card spinner.
- `borderGlow` — border-color oscillation. Used by idle drop zone.

---

## 2. Splash Screen — Removed

`SplashScreen` component and `showSplash` state removed from `App.jsx`. App renders directly into `LandingView` on load.

---

## 3. Landing Page (`App.jsx`, `App.css`)

### Staggered entrance animation
All hero elements animate in sequentially on mount using `animation-delay`:
1. Badge — delay 50ms
2. Title — delay 120ms
3. Subtitle — delay 190ms
4. Drop zone — delay 260ms
5. Pipeline steps — delay 330ms

Each uses `slideInUp` with `var(--ease-out-expo)` and `var(--dur-slow)`.

### Drop zone
- Idle state: slow `borderGlow` pulse (3s cycle) on the dashed border
- Drag-over: `transform: scale(1.015)` + border snaps to `var(--accent)` + `background: var(--accent-dim)`
- Uploading: spinner + "Starting agent..." text, cursor `wait`

### Pipeline steps
No behavior change — purely CSS polish. Labels stay `font-family: monospace`, arrows stay static. Stagger in with the rest of the hero.

---

## 4. Sidebar (`Sidebar.jsx`, `Sidebar.css`)

### Collapsible behavior
- Default: **expanded** (260px)
- Collapsed: 52px icon rail showing logo mark + KB icon + active job dot
- Toggle: arrow tab on the right edge of the sidebar (`‹` / `›`)
- Transition: `width var(--dur-base) var(--ease-out-expo)` on `.sidebar`. `overflow: hidden`. Text/labels fade out with `opacity` transition.

### Collapsed state contents (52px)
- TF logo mark (28px)
- KB icon (SVG)
- Active job glow dot (bottom, only when job active)

### Expanded state changes
- **Job status card** (replaces current `job-card`):
  - Glowing dot (`glowPulse`) beside filename when job active
  - Status line: lowercase word + animated `•••` dots (`dotTrail` keyframe, 3 spans with 200ms stagger)
  - Progress bar: `width` transitions from 0 → current% on mount via `barSlide` keyframe
- **KB list**: items stagger in with 70ms `animation-delay` increments using `slideInLeft`
- **Token meter**: unchanged functionally, gets `var(--surface-raised)` background

---

## 5. Tool Call Cards — ChatView (`ChatView.jsx`, `ChatView.css`)

This is the primary UI upgrade. Replaces the current flat message list with structured expandable cards.

### Card states

**Pending** — dim card, no left border, no icon fill
```
opacity: 0.45 | background: #0f0f0f | border: #1a1a1a
```

**Active** — indigo left border with glow, spinner, `•••` status
```
border-left: 2px solid var(--accent) + box-shadow glow
spinner: spinRing animation
status: "drafting •••" (dotTrail stagger)
live progress bar: 1.5px bar at card bottom, CSS animation from 0→85% over a per-tool estimated duration (analyse: 12s, retrieve: 18s, draft: 40s, finalise: 20s), holds at 85% until completion status arrives, then jumps to 100%
```

**Done (collapsed)** — green left border, checkmark icon, elapsed time, `›` expand hint
```
border-left: 2px solid var(--green)
icon: green checkmark in rounded square
```

**Done (expanded)** — same header + structured output body slides open
```
expandDown animation on body
output: monospace key→value pairs from tool result
click header to toggle
```

### Card rendering strategy
All 4 pipeline step cards are rendered upfront when `ChatView` mounts (steps are hardcoded: `analyse_tender → retrieve_context → draft_sections → finalise`). Cards start in **pending** state and transition to active/done as SSE status arrives. This matches the approved mockup showing all steps visible simultaneously.

The existing `messages` array continues to carry user messages, `agent-done`, `done`, and `error` entries — these render above/below the tool card list as before. The `agent` message type and `activeToolCall` indicator are replaced by the card states.

### Data displayed per tool (expanded state)
- `analyse_tender`: sections array, compliance_items count, dimension_weights
- `retrieve_context`: chunks_retrieved count, sources list
- `draft_sections`: sections drafted, word counts
- `finalise`: final_score, output filename

---

## 6. Review Panel (`ReviewPanel.jsx`, `ReviewPanel.css`)

### Mode toggle (Edit / Split / Preview)
Replace current `background` swap with a **sliding pill**:
- Container: `position: relative; background: #0f0f0f; border: 1px solid var(--border)`
- Pill: `position: absolute` element, `width: 33.33%`, `transform: translateX(0|100%|200%)` driven by `viewMode` state
- Transition: `transform var(--dur-base) var(--ease-out-expo)`
- Button text: active button gets `color: #fff`, others get `color: var(--text-dim)`

### Section navigation
- Active item: add animated left accent bar (`::before` pseudo, `height: 0 → 100%` via `expandDown`, `background: var(--accent)`, `width: 2px`)
- Hover: `background: var(--surface-hover)` (unchanged)
- Entry: section items stagger in with `slideInUp` on ReviewPanel mount

### Reiterate panel
Replace current static appearance with `expandDown` animation on open. Smooth `max-height` transition — no layout jump.

### View transitions (App-level)
Between `LandingView → ChatView → ReviewPanel`:
- Outgoing view: `opacity: 1 → 0; translateY(0 → -8px)` over 180ms
- Incoming view: `slideInUp` 220ms
- Implemented via CSS class toggling on `.app-main` children

---

## 7. Implementation Approach

- **Pure CSS** — no Framer Motion, no GSAP, no new npm dependencies
- All animations via `@keyframes` + CSS custom properties for timing
- Collapsible sidebar state: React `useState(true)` for `expanded`, CSS handles the visual
- Sliding pill: CSS `transform: translateX` driven by inline style or CSS class
- Tool card expand/collapse: React `useState` per card id, `max-height` transition

## 8. Files Changed

| File | Change |
|------|--------|
| `frontend/src/index.css` | Add tokens, keyframes |
| `frontend/src/App.jsx` | Remove splash, add view transitions, stagger landing |
| `frontend/src/App.css` | Landing animations, drop zone glow, pipeline polish |
| `frontend/src/components/Sidebar.jsx` | Add collapsed state, toggle button |
| `frontend/src/components/Sidebar.css` | Collapsible width transition, job card redesign, KB stagger |
| `frontend/src/components/ChatView.jsx` | Replace message list with tool card components |
| `frontend/src/components/ChatView.css` | All tool card styles |
| `frontend/src/components/ReviewPanel.jsx` | Sliding pill toggle logic |
| `frontend/src/components/ReviewPanel.css` | Pill styles, section nav accent bar, reiterate expandDown |
