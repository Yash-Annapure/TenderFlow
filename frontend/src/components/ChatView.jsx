import { useState, useEffect, useRef } from 'react'
import ScoreCard from './ScoreCard'
import './ChatView.css'

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

export default function ChatView({ job, messages, activeToolCall, onReset }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activeToolCall])

  // Non-tool messages: user, agent-done, done, error (agent messages with tool prop are shown by pipeline)
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

        {/* Tool pipeline — all 4 steps shown upfront */}
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

function ToolPipeline({ messages, activeToolCall, job }) {
  const [expanded, setExpanded] = useState({})

  const toggleExpanded = (key) =>
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }))

  const doneTools = new Set(
    messages.filter(m => m.type === 'agent' && m.tool).map(m => m.tool)
  )

  return (
    <div className="tool-pipeline">
      {PIPELINE_STEPS.map((step) => {
        const isDone    = doneTools.has(step.key) && activeToolCall !== step.key
        const isActive  = activeToolCall === step.key
        const isPending = !isDone && !isActive
        const isOpen    = expanded[step.key] ?? false

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
        {isDone && elapsed > 0 && <span className="tool-card-elapsed">{elapsed}s</span>}
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
      if (startRef.current) {
        setElapsed(((Date.now() - startRef.current) / 1000).toFixed(1))
        startRef.current = null
      }
    }
  }, [active])

  return elapsed
}

function Message({ msg }) {
  if (msg.type === 'user') {
    return (
      <div className="msg msg--user">
        <div className="msg-bubble msg-bubble--user">{msg.text}</div>
      </div>
    )
  }

  if (msg.type === 'agent') {
    return (
      <div className="msg msg--agent">
        <div className="msg-agent-icon">🤖</div>
        <div className="msg-content">
          <div className="msg-tool-badge" style={{ color: '#6366f1' }}>
            <span className="msg-tool-fn">{msg.tool || 'agent'}</span>
          </div>
          <div className="msg-heading">{msg.heading}</div>
          <div className="msg-text">{msg.text}</div>
        </div>
      </div>
    )
  }

  if (msg.type === 'agent-done') {
    return (
      <div className="msg msg--agent">
        <div className="msg-agent-icon">✅</div>
        <div className="msg-content">
          <div className="msg-heading">{msg.heading}</div>
          <div className="msg-text">{msg.text}</div>
          {msg.score && <ScoreCard score={msg.score} compact />}
        </div>
      </div>
    )
  }

  if (msg.type === 'done') {
    return (
      <div className="msg msg--agent">
        <div className="msg-agent-icon">🎉</div>
        <div className="msg-content">
          <div className="msg-heading">{msg.heading}</div>
          <div className="msg-text">{msg.text}</div>
          <a
            href={`/tender/${msg.tenderId}/download`}
            className="download-btn"
            download
          >
            <DownloadIcon />
            Download DOCX
          </a>
        </div>
      </div>
    )
  }

  if (msg.type === 'error') {
    return (
      <div className="msg msg--error">
        <span className="msg-error-icon">⚠</span>
        <span>{msg.text}</span>
      </div>
    )
  }

  return null
}

function StatusPill({ status }) {
  if (!status) return null
  const classes = `status-pill status-pill--${status}`
  return <span className={classes}>{status}</span>
}

function FileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}
