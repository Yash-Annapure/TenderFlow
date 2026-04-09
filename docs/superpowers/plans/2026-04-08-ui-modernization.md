# TenderFlow UI Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the TenderFlow React frontend with a Precision Dark aesthetic — animated tool call cards, collapsible sidebar, sliding review panel toggle, staggered landing page, and removal of the splash screen.

**Architecture:** Pure CSS animations using `@keyframes` + CSS custom properties. No new npm dependencies. React state drives which CSS classes/inline styles are applied; CSS handles all motion. Tool call cards replace the current flat message list in ChatView, deriving state from the existing `messages` array and `activeToolCall` prop.

**Tech Stack:** React 18, Vite, plain CSS (no Tailwind, no Framer Motion). Run dev server with `cd frontend && npm run dev`.

---

## File Map

| File | What changes |
|------|-------------|
| `frontend/src/index.css` | Add animation tokens (CSS vars + keyframes) |
| `frontend/src/App.jsx` | Remove splash, add landing stagger classes |
| `frontend/src/App.css` | Landing stagger, drop zone glow, remove `.splash*` |
| `frontend/src/components/Sidebar.jsx` | Add `collapsed` state + toggle button, redesign job card |
| `frontend/src/components/Sidebar.css` | Collapse transition, job card redesign, KB stagger |
| `frontend/src/components/ChatView.jsx` | Replace tool indicator with `ToolPipeline` + `ToolCard` components |
| `frontend/src/components/ChatView.css` | Tool card styles (all states), remove old `.tool-running*` |
| `frontend/src/components/ReviewPanel.jsx` | Sliding pill toggle + section nav accent state |
| `frontend/src/components/ReviewPanel.css` | Pill styles, nav accent bar, reiterate expandDown |

---

## Task 1: CSS Animation Tokens

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add custom properties and keyframes to `index.css`**

Open `frontend/src/index.css`. After the `:root { ... }` block (after line 30), add:

```css
/* ── Animation tokens ────────────────────────────────────────────────────── */
:root {
  --ease-out-expo:  cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring:    cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-in-out:    cubic-bezier(0.4, 0, 0.2, 1);
  --dur-fast:       120ms;
  --dur-base:       220ms;
  --dur-slow:       380ms;
  --glow-accent:    0 0 0 3px rgba(99, 102, 241, 0.18);
  --surface-raised: #161616;
}
```

Then replace the existing `@keyframes` block at the bottom of `index.css` (currently lines 74–76) with:

```css
@keyframes fadeIn    { from { opacity: 0 }                                    to { opacity: 1 } }
@keyframes fadeOut   { from { opacity: 1; pointer-events: all }               to { opacity: 0; pointer-events: none } }
@keyframes slideUp   { from { opacity: 0; transform: translateY(20px) }       to { opacity: 1; transform: translateY(0) } }
@keyframes slideInUp { from { opacity: 0; transform: translateY(14px) }       to { opacity: 1; transform: translateY(0) } }
@keyframes slideInLeft { from { opacity: 0; transform: translateX(-10px) }    to { opacity: 1; transform: translateX(0) } }
@keyframes expandDown {
  from { max-height: 0; opacity: 0 }
  to   { max-height: 400px; opacity: 1 }
}
@keyframes spinRing  { to { transform: rotate(360deg) } }
@keyframes glowPulse {
  0%, 100% { box-shadow: 0 0 4px rgba(99,102,241,0.6) }
  50%       { box-shadow: 0 0 12px rgba(99,102,241,0.9) }
}
@keyframes dotTrail {
  0%, 100% { opacity: 0.25; transform: scale(0.7) }
  50%      { opacity: 1;    transform: scale(1) }
}
@keyframes borderGlow {
  0%, 100% { border-color: var(--border-light) }
  50%      { border-color: rgba(99, 102, 241, 0.4) }
}
@keyframes barSlide  { from { width: 0 }   to { width: var(--bar-target, 100%) } }
@keyframes shimmer   {
  0%   { background-position: 200% center }
  100% { background-position: -200% center }
}
```

- [ ] **Step 2: Verify dev server starts cleanly**

```bash
cd "E:/Github Projects/Q-Hack/TenderFlow/frontend" && npm run dev
```

Expected: server starts on `http://localhost:5173` (or similar), no CSS parse errors in terminal.

- [ ] **Step 3: Commit**

```bash
cd "E:/Github Projects/Q-Hack/TenderFlow" && git add frontend/src/index.css && git commit -m "feat: add CSS animation token system and keyframes"
```

---

## Task 2: Remove Splash Screen

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Remove splash state and render from `App.jsx`**

In `frontend/src/App.jsx`, remove line 14:
```js
const [showSplash,     setShowSplash]     = useState(true)
```

Remove line 128:
```js
if (showSplash) return <SplashScreen onDone={() => setShowSplash(false)} />
```

Remove the entire `SplashScreen` function (lines 233–252):
```js
function SplashScreen({ onDone }) {
  // ... entire function
}
```

- [ ] **Step 2: Remove splash CSS from `App.css`**

In `frontend/src/App.css`, remove the entire `/* ── Splash screen ── */` section (lines 172–252 — everything from `.splash {` through the closing `}`  of `@keyframes splashProgress`).

- [ ] **Step 3: Verify app loads directly to landing**

Run `npm run dev`. Open `http://localhost:5173`. App should render the landing page immediately with no splash delay.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/App.css && git commit -m "feat: remove splash screen, land directly on upload page"
```

---

## Task 3: Landing Page Stagger Animations

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add stagger animation classes to `LandingView` in `App.jsx`**

Replace the `LandingView` return JSX (the `<div className="landing">...</div>` block starting at line 182) with:

```jsx
return (
  <div className="landing">
    <div className="landing-hero">
      <div className="landing-badge landing-stagger-1">AI-Powered Tender Agent</div>
      <h1 className="landing-title landing-stagger-2">TenderFlow</h1>
      <p className="landing-sub landing-stagger-3">
        Upload your tender document. The agent analyses structure, retrieves
        knowledge base context, drafts all sections, and prepares a scored
        response — ready for your human review.
      </p>

      <div
        className={`drop-zone landing-stagger-4 ${dragging ? 'drop-zone--active' : ''} ${uploading ? 'drop-zone--uploading' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]) }}
        onClick={() => !uploading && inputRef.current?.click()}
      >
        <input ref={inputRef} type="file" accept=".pdf,.txt,.docx" style={{ display: 'none' }}
          onChange={(e) => handleFile(e.target.files[0])} />
        {uploading ? (
          <div className="drop-zone-content">
            <Spinner size={32} />
            <span className="drop-zone-text">Starting agent...</span>
          </div>
        ) : (
          <div className="drop-zone-content">
            <UploadIcon />
            <span className="drop-zone-text">
              {dragging ? 'Drop to upload' : 'Drop tender PDF here, or click to browse'}
            </span>
            <span className="drop-zone-hint">PDF · DOCX · TXT</span>
          </div>
        )}
      </div>

      {error && <div className="landing-error landing-stagger-4">{error}</div>}

      <div className="landing-pipeline landing-stagger-5">
        {['analyse_tender', 'retrieve_context', 'draft_sections', 'human_review', 'finalise'].map((step, i) => (
          <div key={step} className="pipeline-step">
            {i > 0 && <div className="pipeline-arrow" />}
            <span className="pipeline-label">{step}</span>
          </div>
        ))}
      </div>
    </div>
  </div>
)
```

- [ ] **Step 2: Add stagger + drop zone polish to `App.css`**

Add the following to the end of the landing section in `frontend/src/App.css` (after `.landing-error { ... }`):

```css
/* ── Landing stagger entrance ───────────────────────────────────────────── */
.landing-stagger-1,
.landing-stagger-2,
.landing-stagger-3,
.landing-stagger-4,
.landing-stagger-5 {
  animation: slideInUp var(--dur-slow, 380ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
  opacity: 0;
}

.landing-stagger-1 { animation-delay: 50ms }
.landing-stagger-2 { animation-delay: 120ms }
.landing-stagger-3 { animation-delay: 190ms }
.landing-stagger-4 { animation-delay: 260ms }
.landing-stagger-5 { animation-delay: 330ms }

/* ── Drop zone polish ───────────────────────────────────────────────────── */
.drop-zone {
  animation: borderGlow 3s ease 1.2s infinite;
  transition: border-color 0.2s, background 0.2s, transform 0.15s var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1));
}

.drop-zone--active {
  transform: scale(1.015);
  animation: none;
}

.drop-zone--uploading {
  animation: none;
}
```

- [ ] **Step 3: Verify stagger in browser**

Reload `http://localhost:5173`. Each hero element should fade+slide in sequentially. Drop zone should have a slow pulsing border glow when idle, and scale slightly on drag-over.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/App.css && git commit -m "feat: staggered landing page entrance + drop zone glow animation"
```

---

## Task 4: Sidebar Collapsible Toggle

**Files:**
- Modify: `frontend/src/components/Sidebar.jsx`
- Modify: `frontend/src/components/Sidebar.css`

- [ ] **Step 1: Add `collapsed` state and toggle button to `Sidebar.jsx`**

In `frontend/src/components/Sidebar.jsx`, add `collapsed` state inside the `Sidebar` component (after line 20):

```js
const [collapsed, setCollapsed] = useState(false)
```

Replace the `<aside className="sidebar">` opening tag and header (lines 81–88) with:

```jsx
<aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
  {/* Toggle tab */}
  <button
    className="sidebar-toggle"
    onClick={() => setCollapsed(v => !v)}
    title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
  >
    {collapsed ? '›' : '‹'}
  </button>

  <div className="sidebar-header">
    <div className="sidebar-logo">
      <span className="sidebar-logo-mark">TF</span>
      {!collapsed && <span className="sidebar-logo-name">TenderFlow</span>}
    </div>
  </div>
```

Also wrap the `<div className="sidebar-section-title">` and all content below the header to hide when collapsed. Replace from `<div className="sidebar-section-title">Knowledge Base</div>` (line 89) through `</aside>` (line 153) with:

```jsx
      {!collapsed && (
        <>
          <div className="sidebar-section-title">Knowledge Base</div>

          <div className="sidebar-kb">
            {loading ? (
              <div className="sidebar-empty">Loading...</div>
            ) : docs.length === 0 ? (
              <div className="sidebar-empty">No documents ingested yet</div>
            ) : (
              Object.entries(grouped).map(([type, items]) => (
                <div key={type} className="kb-group">
                  <div className="kb-group-label" style={{ color: DOC_TYPE_COLORS[type] || '#8e8ea0' }}>
                    {DOC_TYPE_LABELS[type] || type}
                    <span className="kb-count">{items.length}</span>
                  </div>
                  {items.map((doc, idx) => (
                    <div key={doc.id} className="kb-doc" style={{ animationDelay: `${idx * 60}ms` }}>
                      <DocIcon type={type} />
                      <div className="kb-doc-info">
                        <span className="kb-doc-name" title={doc.filename}>{doc.source_name || doc.filename}</span>
                        <span className="kb-doc-meta">{doc.chunk_count ?? '—'} chunks</span>
                      </div>
                      <StatusDot status={doc.status} />
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>

          {tokenLog && <TokenMeter tokenLog={tokenLog} />}

          <div className="sidebar-footer">
            <button className="sidebar-add-btn" onClick={() => setShowModal(true)}>
              <PlusIcon />
              Add Document
            </button>
          </div>
        </>
      )}

      {collapsed && (
        <div className="sidebar-collapsed-spacer">
          {currentJob && currentJob.status !== 'done' && currentJob.status !== 'error' && (
            <div className="sidebar-collapsed-job-dot" />
          )}
        </div>
      )}

      {showModal && (
        <IngestModal
          onClose={() => { setShowModal(false); setUploadError(null) }}
          onSubmit={handleIngest}
          uploading={uploading}
          error={uploadError}
        />
      )}
    </aside>
```

- [ ] **Step 2: Add collapse CSS to `Sidebar.css`**

Replace the `.sidebar { ... }` rule at the top of `frontend/src/components/Sidebar.css` with:

```css
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  position: relative;
  transition: width var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)),
              min-width var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1));
}

.sidebar--collapsed {
  width: 52px;
  min-width: 52px;
}
```

Then add the toggle tab and collapsed spacer styles after the `.sidebar-header` block:

```css
/* ── Toggle tab ─────────────────────────────────────────────────────────── */
.sidebar-toggle {
  position: absolute;
  right: -13px;
  top: 50%;
  transform: translateY(-50%);
  width: 13px;
  height: 36px;
  background: var(--surface-raised, #161616);
  border: 1px solid var(--border-light);
  border-left: none;
  border-radius: 0 5px 5px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 10;
  color: var(--text-dim);
  font-size: 10px;
  padding: 0;
  transition: color 0.15s, background 0.15s;
}

.sidebar-toggle:hover {
  color: var(--text);
  background: var(--surface-hover);
}

.sidebar-collapsed-spacer {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  padding-bottom: 16px;
}

.sidebar-collapsed-job-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: glowPulse 1.5s ease infinite;
}
```

Also add stagger animation to `.kb-doc`:

```css
.kb-doc {
  animation: slideInLeft var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
}
```

- [ ] **Step 3: Verify toggle in browser**

Click the `‹` tab — sidebar should smoothly collapse to 52px. Click `›` to expand. No layout jump.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar.jsx frontend/src/components/Sidebar.css && git commit -m "feat: collapsible sidebar with animated toggle tab"
```

---

## Task 5: Sidebar Job Status Card Redesign

**Files:**
- Modify: `frontend/src/components/Sidebar.jsx`
- Modify: `frontend/src/components/Sidebar.css`

The current job card is at the bottom of the sidebar. Move it to just below the header and redesign with animated status.

- [ ] **Step 1: Replace job card JSX in `Sidebar.jsx`**

In the `!collapsed` block (Task 4), insert the new job card right after `</div>` that closes `sidebar-header`, before `<div className="sidebar-section-title">`. 

Find in the `!collapsed` fragment the `<div className="sidebar-section-title">Knowledge Base</div>` and insert above it:

```jsx
{currentJob && (
  <JobStatusCard job={currentJob} />
)}
```

Then add the `JobStatusCard` component as a new function at the bottom of the file (before `function IngestModal`):

```jsx
const STEP_LABELS = {
  analysing:       { tool: 'analyse_tender',   label: 'analysing' },
  retrieving:      { tool: 'retrieve_context', label: 'retrieving' },
  drafting:        { tool: 'draft_sections',   label: 'drafting' },
  finalising:      { tool: 'finalise',         label: 'finalising' },
  awaiting_review: { tool: null,               label: 'review ready' },
  done:            { tool: null,               label: 'complete' },
  error:           { tool: null,               label: 'error' },
}

const STEP_ORDER = ['analysing', 'retrieving', 'drafting', 'finalising']

function JobStatusCard({ job }) {
  const meta = STEP_LABELS[job.status] || { label: job.status }
  const stepIdx = STEP_ORDER.indexOf(job.status)
  const progressPct = stepIdx === -1
    ? (job.status === 'awaiting_review' || job.status === 'done' ? 100 : 0)
    : Math.round(((stepIdx + 0.5) / STEP_ORDER.length) * 100)

  const isActive = stepIdx !== -1
  const isDone   = job.status === 'done' || job.status === 'awaiting_review'
  const isError  = job.status === 'error'

  const dotColor = isError ? 'var(--red)' : isDone ? 'var(--green)' : 'var(--accent)'

  return (
    <div className="job-status-card">
      <div className="job-status-card-row">
        <div className="job-status-dot" style={{ background: dotColor, boxShadow: isActive ? `0 0 6px ${dotColor}` : 'none' }} />
        <span className="job-status-filename">{job.tender_filename || 'tender.pdf'}</span>
      </div>
      <div className="job-status-label">
        {meta.label}
        {isActive && (
          <span className="job-status-dots">
            <span style={{ animationDelay: '0ms' }} />
            <span style={{ animationDelay: '180ms' }} />
            <span style={{ animationDelay: '360ms' }} />
          </span>
        )}
        {isDone && job.score_json?.final_score != null && (
          <span className="job-status-score">{job.score_json.final_score.toFixed(1)}/100</span>
        )}
      </div>
      <div className="job-status-bar-track">
        <div
          className="job-status-bar-fill"
          style={{ '--bar-target': `${progressPct}%` }}
        />
      </div>
    </div>
  )
}
```

Also remove the old `{currentJob && (...)}` block that was previously at the bottom of the sidebar (the `sidebar-job` div with `job-card`).

- [ ] **Step 2: Add job status card CSS to `Sidebar.css`**

Replace the entire `/* ── Active job card ── */` section (`.sidebar-job`, `.job-card`, `.job-filename`, `.job-status`, `.job-score`) with:

```css
/* ── Job status card ────────────────────────────────────────────────────── */
.job-status-card {
  margin: 8px 10px 4px;
  background: var(--surface-raised, #161616);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: var(--radius);
  padding: 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex-shrink: 0;
}

.job-status-card-row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.job-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  animation: glowPulse 1.5s ease infinite;
}

.job-status-filename {
  font-size: 11px;
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.job-status-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--text-muted);
}

.job-status-dots {
  display: inline-flex;
  gap: 3px;
  align-items: center;
}

.job-status-dots span {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--accent);
  display: inline-block;
  animation: dotTrail 1.2s ease infinite;
}

.job-status-score {
  margin-left: auto;
  font-size: 10px;
  color: var(--green);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.job-status-bar-track {
  height: 2px;
  background: var(--border);
  border-radius: 1px;
  overflow: hidden;
}

.job-status-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), #818cf8);
  border-radius: 1px;
  animation: barSlide 1s var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
}
```

- [ ] **Step 3: Verify job card in browser**

Upload a tender file. The job card should appear below the header with a glowing dot, `analysing •••` label, and an animated progress bar. Bar should jump forward as status transitions.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar.jsx frontend/src/components/Sidebar.css && git commit -m "feat: animated sidebar job status card with progress bar and dot trail"
```

---

## Task 6: ChatView Tool Pipeline Cards — Logic

**Files:**
- Modify: `frontend/src/components/ChatView.jsx`

Replace the current flat message-based tool display with a `ToolPipeline` component that shows all 4 steps upfront.

- [ ] **Step 1: Add tool card state helpers and constants at top of `ChatView.jsx`**

Replace the current `TOOL_META` constant (lines 5–10) with:

```js
const PIPELINE_STEPS = [
  { key: 'analyse_tender',   label: 'analyse_tender',   desc: 'Extracting tender structure' },
  { key: 'retrieve_context', label: 'retrieve_context', desc: 'Querying knowledge base' },
  { key: 'draft_sections',   label: 'draft_sections',   desc: 'Drafting response sections' },
  { key: 'finalise',         label: 'finalise',         desc: 'Finalising document' },
]

// Estimated duration (ms) for progress bar animation per step
const STEP_DURATION = {
  analyse_tender:   12000,
  retrieve_context: 18000,
  draft_sections:   40000,
  finalise:         20000,
}
```

- [ ] **Step 2: Add `ToolPipeline` and `ToolCard` components to `ChatView.jsx`**

Add these components before the closing of the file (before the `StatusPill` function):

```jsx
function ToolPipeline({ messages, activeToolCall, job }) {
  const [expanded, setExpanded] = useState({})

  const toggleExpanded = (key) =>
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }))

  // Derive done tools from messages array
  const doneTools = new Set(
    messages.filter(m => m.type === 'agent' && m.tool).map(m => m.tool)
  )

  return (
    <div className="tool-pipeline">
      {PIPELINE_STEPS.map((step) => {
        const isDone   = doneTools.has(step.key)
        const isActive = activeToolCall === step.key
        const isPending = !isDone && !isActive
        const isOpen   = expanded[step.key] ?? false

        return (
          <ToolCard
            key={step.key}
            step={step}
            isDone={isDone}
            isActive={isActive}
            isPending={isPending}
            isOpen={isOpen}
            onToggle={() => isDone && toggleExpanded(step.key)}
            job={job}
          />
        )
      })}
    </div>
  )
}

function ToolCard({ step, isDone, isActive, isPending, isOpen, onToggle, job }) {
  const elapsed = useElapsedTimer(isActive)

  let borderColor = 'transparent'
  if (isActive) borderColor = 'var(--accent)'
  if (isDone)   borderColor = 'var(--green)'

  return (
    <div
      className={[
        'tool-card',
        isDone    && 'tool-card--done',
        isActive  && 'tool-card--active',
        isPending && 'tool-card--pending',
      ].filter(Boolean).join(' ')}
      style={{ '--card-border-color': borderColor }}
    >
      <div className="tool-card-header" onClick={onToggle}>
        <ToolCardIcon isDone={isDone} isActive={isActive} />
        <span className="tool-card-name">{step.label}</span>
        {isActive && (
          <span className="tool-card-status">
            {step.desc.split(' ')[0].toLowerCase()}
            <span className="tool-card-dots">
              <span style={{ animationDelay: '0ms' }} />
              <span style={{ animationDelay: '180ms' }} />
              <span style={{ animationDelay: '360ms' }} />
            </span>
          </span>
        )}
        {isDone && <span className="tool-card-elapsed">{elapsed}s</span>}
        {isDone && (
          <span className="tool-card-chevron">{isOpen ? '▾' : '›'}</span>
        )}
        {isActive && <span className="tool-card-elapsed tool-card-elapsed--active">{elapsed}s</span>}
      </div>

      {isActive && (
        <div
          className="tool-card-progress"
          style={{ '--step-duration': `${STEP_DURATION[step.key]}ms` }}
        />
      )}

      {isDone && isOpen && (
        <div className="tool-card-output">
          <ToolOutput stepKey={step.key} job={job} />
        </div>
      )}
    </div>
  )
}

function ToolCardIcon({ isDone, isActive }) {
  if (isDone) return (
    <div className="tool-card-icon tool-card-icon--done">
      <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
        <polyline points="2,6 5,9 10,3" stroke="var(--green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </div>
  )
  if (isActive) return <div className="tool-card-icon tool-card-icon--spinner" />
  return <div className="tool-card-icon tool-card-icon--pending" />
}

function ToolOutput({ stepKey, job }) {
  const lines = []
  if (stepKey === 'analyse_tender') {
    const sections = job?.sections_json?.map(s => s.section_name) ?? []
    lines.push(['sections', sections.length ? JSON.stringify(sections) : '—'])
    const compliance = job?.score_json?.compliance_score ?? null
    if (compliance != null) lines.push(['compliance_score', compliance.toFixed(1)])
  }
  if (stepKey === 'retrieve_context') {
    lines.push(['status', 'context retrieved'])
  }
  if (stepKey === 'draft_sections') {
    const count = job?.sections_json?.length ?? '—'
    lines.push(['sections_drafted', String(count)])
  }
  if (stepKey === 'finalise') {
    const score = job?.score_json?.final_score ?? null
    if (score != null) lines.push(['final_score', `${score.toFixed(1)}/100`])
    if (job?.tender_filename) lines.push(['output', job.tender_filename.replace(/\.[^.]+$/, '.docx')])
  }
  if (lines.length === 0) lines.push(['status', 'done'])

  return (
    <div className="tool-output-lines">
      {lines.map(([k, v]) => (
        <div key={k} className="tool-output-line">
          <span className="tool-output-arrow">→</span>
          <span className="tool-output-key">{k}</span>
          <span className="tool-output-val">{v}</span>
        </div>
      ))}
    </div>
  )
}

function useElapsedTimer(active) {
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(null)

  useEffect(() => {
    if (active) {
      startRef.current = Date.now()
      const id = setInterval(() => {
        setElapsed(((Date.now() - startRef.current) / 1000).toFixed(1))
      }, 100)
      return () => clearInterval(id)
    } else {
      // freeze on last value when done
      if (startRef.current) {
        setElapsed(((Date.now() - startRef.current) / 1000).toFixed(1))
        startRef.current = null
      }
    }
  }, [active])

  return elapsed
}
```

- [ ] **Step 3: Update `ChatView` main component to use `ToolPipeline`**

Replace the entire `ChatView` default export function body with:

```jsx
export default function ChatView({ job, messages, activeToolCall, onReset }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activeToolCall])

  // Non-tool messages: user, agent-done, done, error
  const displayMessages = messages.filter(
    m => m.type !== 'agent' || !m.tool
  )

  return (
    <div className="chat-view">
      <div className="chat-topbar">
        <div className="chat-topbar-title">
          <FileIcon />
          <span>{job?.tender_filename || 'Tender'}</span>
          <StatusPill status={job?.status} />
        </div>
        <button className="chat-new-btn" onClick={onReset}>+ New Tender</button>
      </div>

      <div className="chat-messages">
        {/* User upload message */}
        {displayMessages.filter(m => m.type === 'user').map(msg => (
          <Message key={msg.id} msg={msg} />
        ))}

        {/* Tool pipeline */}
        <div className="msg msg--pipeline">
          <ToolPipeline messages={messages} activeToolCall={activeToolCall} job={job} />
        </div>

        {/* Final state messages: agent-done, done, error */}
        {displayMessages.filter(m => m.type !== 'user').map(msg => (
          <Message key={msg.id} msg={msg} />
        ))}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
```

Also add `useState` to the existing import at the top of `ChatView.jsx` (currently only `useEffect, useRef`):
```js
import { useState, useEffect, useRef } from 'react'
```

- [ ] **Step 4: Verify no runtime errors**

Open browser console at `http://localhost:5173`. Upload a file — no JS errors. Pipeline cards should appear (may be unstyled until Task 7).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatView.jsx && git commit -m "feat: tool pipeline card component with active/done/pending states"
```

---

## Task 7: ChatView Tool Card CSS

**Files:**
- Modify: `frontend/src/components/ChatView.css`

- [ ] **Step 1: Replace `.tool-running*` section and add card styles**

In `frontend/src/components/ChatView.css`, remove the entire `/* ── Active tool call indicator ── */` section (`.tool-running`, `@keyframes pulse`, `.tool-running-dot`, `.tool-running-name`, `.tool-running-name code`, `.tool-running-desc`).

Add in its place:

```css
/* ── Tool pipeline ──────────────────────────────────────────────────────── */
.msg--pipeline {
  padding: 0 24px;
}

.tool-pipeline {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 672px;
  width: 100%;
}

/* ── Tool card base ─────────────────────────────────────────────────────── */
.tool-card {
  border-radius: 9px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--surface);
  position: relative;
  animation: slideInUp var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
}

.tool-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--card-border-color, transparent);
  border-radius: 2px 0 0 2px;
  transition: background 0.3s;
}

/* ── Card states ─────────────────────────────────────────────────────────── */
.tool-card--pending {
  background: #0f0f0f;
  border-color: #1a1a1a;
  opacity: 0.45;
}

.tool-card--active {
  border-color: rgba(99, 102, 241, 0.2);
}

.tool-card--active::before {
  box-shadow: 0 0 6px rgba(99, 102, 241, 0.5);
}

/* ── Card header ─────────────────────────────────────────────────────────── */
.tool-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 13px 10px 16px;
  cursor: default;
}

.tool-card--done .tool-card-header {
  cursor: pointer;
}

.tool-card-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  font-family: 'Courier New', monospace;
  flex: 1;
}

.tool-card--pending .tool-card-name {
  color: var(--text-dim);
  font-weight: 500;
}

.tool-card-status {
  font-size: 10px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 4px;
}

.tool-card-dots {
  display: inline-flex;
  gap: 3px;
  align-items: center;
}

.tool-card-dots span {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--accent);
  display: inline-block;
  animation: dotTrail 1.2s ease infinite;
}

.tool-card-elapsed {
  font-size: 10px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.tool-card-elapsed--active {
  color: var(--accent);
}

.tool-card-chevron {
  font-size: 10px;
  color: var(--text-dim);
  margin-left: 2px;
}

/* ── Card icons ──────────────────────────────────────────────────────────── */
.tool-card-icon {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.tool-card-icon--done {
  background: rgba(16, 163, 127, 0.15);
  border: 1px solid rgba(16, 163, 127, 0.3);
}

.tool-card-icon--spinner {
  border: 1.5px solid rgba(99, 102, 241, 0.2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spinRing 0.7s linear infinite;
}

.tool-card-icon--pending {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
}

/* ── Live progress bar ───────────────────────────────────────────────────── */
.tool-card-progress {
  height: 1.5px;
  background: #1a1a1a;
  overflow: hidden;
}

.tool-card-progress::after {
  content: '';
  display: block;
  height: 100%;
  width: 85%;
  background: linear-gradient(90deg, var(--accent), #818cf8);
  animation: barSlide var(--step-duration, 20000ms) var(--ease-in-out, cubic-bezier(0.4,0,0.2,1)) both;
}

/* ── Expandable output ───────────────────────────────────────────────────── */
.tool-card-output {
  border-top: 1px solid #1a1a1a;
  padding: 9px 16px 11px;
  animation: expandDown var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
}

.tool-output-lines {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.tool-output-line {
  display: flex;
  align-items: baseline;
  gap: 7px;
  font-size: 10px;
  font-family: 'Courier New', monospace;
  line-height: 1.8;
}

.tool-output-arrow {
  color: var(--border-light);
  flex-shrink: 0;
}

.tool-output-key {
  color: var(--text-dim);
  flex-shrink: 0;
}

.tool-output-val {
  color: var(--text-muted);
  word-break: break-all;
}
```

- [ ] **Step 2: Verify card visuals**

Upload a tender. Cards should:
- All 4 appear with pending state (dim)
- Active card gets indigo left border + spinner + dots + live progress bar
- Done cards turn green with checkmark, click to expand output

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChatView.css && git commit -m "feat: tool card CSS with all states, progress bar, and expandable output"
```

---

## Task 8: Review Panel Sliding Pill Toggle

**Files:**
- Modify: `frontend/src/components/ReviewPanel.jsx`
- Modify: `frontend/src/components/ReviewPanel.css`

- [ ] **Step 1: Replace view toggle JSX in `ReviewPanel.jsx`**

Find the `<div className="view-toggle">` block (lines 136–139) and replace with:

```jsx
<div className="view-toggle">
  <div
    className="view-toggle-pill"
    style={{ transform: `translateX(${viewMode === 'edit' ? '0%' : viewMode === 'split' ? '100%' : '200%'})` }}
  />
  <button
    className={`view-toggle-btn ${viewMode === 'edit' ? 'active' : ''}`}
    onClick={() => setViewMode('edit')}
  >Edit</button>
  <button
    className={`view-toggle-btn ${viewMode === 'split' ? 'active' : ''}`}
    onClick={() => setViewMode('split')}
  >Split</button>
  <button
    className={`view-toggle-btn ${viewMode === 'preview' ? 'active' : ''}`}
    onClick={() => setViewMode('preview')}
  >Preview</button>
</div>
```

- [ ] **Step 2: Update view toggle CSS in `ReviewPanel.css`**

Replace the entire `/* View mode toggle */` section (`.view-toggle`, `.view-toggle-btn`, `.view-toggle-btn:last-child`, `.view-toggle-btn:hover`, `.view-toggle-btn.active`) with:

```css
/* ── Sliding pill toggle ────────────────────────────────────────────────── */
.view-toggle {
  display: flex;
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  overflow: hidden;
  flex-shrink: 0;
  background: var(--bg);
  position: relative;
}

.view-toggle-pill {
  position: absolute;
  top: 0;
  left: 0;
  width: 33.333%;
  height: 100%;
  background: var(--accent);
  border-radius: calc(var(--radius) - 1px);
  transition: transform var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1));
  pointer-events: none;
  z-index: 0;
}

.view-toggle-btn {
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 500;
  background: none;
  color: var(--text-dim);
  transition: color var(--dur-fast, 120ms);
  border-right: 1px solid var(--border-light);
  position: relative;
  z-index: 1;
}

.view-toggle-btn:last-child {
  border-right: none;
}

.view-toggle-btn:hover {
  color: var(--text);
}

.view-toggle-btn.active {
  color: #fff;
}
```

- [ ] **Step 3: Verify pill animation**

Open the review panel (after a tender is drafted). Click Edit/Split/Preview — the indigo pill should slide smoothly between options. Active button text turns white.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ReviewPanel.jsx frontend/src/components/ReviewPanel.css && git commit -m "feat: sliding pill toggle for review panel view modes"
```

---

## Task 9: Review Panel Section Nav Accent + Reiterate Animation

**Files:**
- Modify: `frontend/src/components/ReviewPanel.css`

- [ ] **Step 1: Add animated active accent bar to section nav items**

In `frontend/src/components/ReviewPanel.css`, replace the `.review-nav-item--active` rule with:

```css
.review-nav-item--active {
  background: var(--accent-dim);
  color: var(--text);
  border: 1px solid rgba(99,102,241,0.3);
  position: relative;
  overflow: hidden;
}

.review-nav-item--active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  width: 2px;
  height: 100%;
  background: var(--accent);
  border-radius: 0 1px 1px 0;
  animation: expandDown var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
}
```

- [ ] **Step 2: Add `expandDown` animation to reiterate panel**

Find `.reiterate-panel` in `ReviewPanel.css` and add `animation`:

```css
.reiterate-panel {
  margin-top: 8px;
  background: var(--surface);
  border: 1px solid rgba(99,102,241,0.3);
  border-radius: var(--radius);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  animation: expandDown var(--dur-base, 220ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
  overflow: hidden;
}
```

- [ ] **Step 3: Verify in browser**

In the review panel, click between sections — the active item should show a smooth left accent bar. Open/close Re-iterate panel — it should expand/collapse smoothly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ReviewPanel.css && git commit -m "feat: animated section nav accent bar and reiterate panel expand"
```

---

## Task 10: App-Level View Transitions

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add enter animation to each main view**

In `frontend/src/App.css`, add at the end:

```css
/* ── View enter animations ───────────────────────────────────────────────── */
.landing,
.chat-view,
.review-layout {
  animation: slideInUp var(--dur-slow, 380ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1)) both;
}
```

This works because React unmounts the old view and mounts the new one when `job` state changes, triggering a fresh animation on each mount.

- [ ] **Step 2: Verify transition in browser**

Go through the full flow: land → upload → watch processing → review panel. Each view should slide in from below when it mounts.

- [ ] **Step 3: Final end-to-end check**

Verify the complete list:
- [ ] Landing stagger works (badge → title → dropzone → pipeline)
- [ ] Drop zone glows on idle, scales on drag-over
- [ ] Sidebar collapses/expands with arrow tab
- [ ] Sidebar job card shows with `analysing •••` dots + progress bar
- [ ] Tool cards appear for all 4 steps, activate in order
- [ ] Done cards show green border + checkmark, click to expand output
- [ ] Active card has spinner + progress bar
- [ ] Review panel pill slides smoothly
- [ ] Section nav shows accent bar on active item
- [ ] Reiterate panel expands with animation
- [ ] No splash screen on load

- [ ] **Step 4: Final commit**

```bash
git add frontend/src/App.css && git commit -m "feat: view enter animations for seamless landing/chat/review transitions"
```

---

## Done

All 10 tasks produce a working, visually complete UI. Demo flow: open app → upload tender → watch animated pipeline → review panel with split view. No dependencies added.
