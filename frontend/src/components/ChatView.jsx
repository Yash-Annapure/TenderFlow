import { useEffect, useRef } from 'react'
import ScoreCard from './ScoreCard'
import './ChatView.css'

const TOOL_META = {
  analyse_tender:   { icon: '🔍', color: '#6366f1', label: 'analyse_tender',   desc: 'Extracting tender structure' },
  retrieve_context: { icon: '🗄️',  color: '#0ea5e9', label: 'retrieve_context', desc: 'Querying knowledge base' },
  draft_sections:   { icon: '✍️',  color: '#10a37f', label: 'draft_sections',   desc: 'Drafting response sections' },
  finalise:         { icon: '✨',  color: '#f59e0b', label: 'finalise',          desc: 'Finalising document' },
}

export default function ChatView({ job, messages, activeToolCall, onReset }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activeToolCall])

  return (
    <div className="chat-view">
      {/* Top bar */}
      <div className="chat-topbar">
        <div className="chat-topbar-title">
          <FileIcon />
          <span>{job?.tender_filename || 'Tender'}</span>
          <StatusPill status={job?.status} />
        </div>
        <button className="chat-new-btn" onClick={onReset}>+ New Tender</button>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.map(msg => (
          <Message key={msg.id} msg={msg} />
        ))}

        {/* Active tool call indicator */}
        {activeToolCall && (
          <div className="tool-running">
            <span className="tool-running-dot" />
            <span className="tool-running-name">
              Calling: <code>{activeToolCall}</code>
            </span>
            <span className="tool-running-desc">
              {TOOL_META[activeToolCall]?.desc}
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
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
    const meta = TOOL_META[msg.tool] || {}
    return (
      <div className="msg msg--agent">
        <div className="msg-agent-icon">{meta.icon || '🤖'}</div>
        <div className="msg-content">
          <div className="msg-tool-badge" style={{ color: meta.color || '#6366f1' }}>
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
