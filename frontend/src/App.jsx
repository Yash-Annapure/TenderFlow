import { useState, useEffect, useRef, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import ReviewPanel from './components/ReviewPanel'
import { startTender, openEventStream } from './api/client.js'
import {
  emptyLog, addOps,
  buildPipelineEstimates,
  buildFinalisationEstimates,
} from './utils/tokens.js'
import './App.css'

export default function App() {
  const [job,            setJob]            = useState(null)
  const [messages,       setMessages]       = useState([])
  const [activeToolCall, setActiveToolCall] = useState(null)
  const [watchingId,     setWatchingId]     = useState(null)
  const [tokenLog,       setTokenLog]       = useState(emptyLog())
  const [history,        setHistory]        = useState([])   // [{id, job, messages, timestamp}]
  const [historyViewId,  setHistoryViewId]  = useState(null) // tender_id being viewed
  const esRef     = useRef(null)
  // Refs so archive callbacks never close over stale state
  const jobRef      = useRef(null)
  const messagesRef = useRef([])
  useEffect(() => { jobRef.current      = job      }, [job])
  useEffect(() => { messagesRef.current = messages }, [messages])

  const pushMessage = useCallback((msg) => {
    setMessages(prev => [...prev, { id: `${Date.now()}-${Math.random()}`, ...msg }])
  }, [])

  const addTokenOps = useCallback((ops) => {
    setTokenLog(prev => addOps(prev, ops))
  }, [])

  // Upsert current session into history (uses refs to avoid stale closures)
  const archiveCurrent = useCallback(() => {
    const j = jobRef.current
    const m = messagesRef.current
    if (!j || m.length === 0) return
    const id = j.tender_id
    setHistory(prev => {
      const idx = prev.findIndex(h => h.id === id)
      const entry = {
        id,
        job:       { ...j },
        messages:  [...m],
        timestamp: idx >= 0 ? prev[idx].timestamp : new Date(),
      }
      if (idx >= 0) {
        const next = [...prev]; next[idx] = entry; return next
      }
      return [entry, ...prev]
    })
  }, [])

  const handleJobStarted = useCallback((newJob, filename) => {
    archiveCurrent()           // snapshot previous session before wiping
    setHistoryViewId(null)     // exit history view if open
    setJob(newJob)
    setTokenLog(emptyLog())
    setMessages([{ id: 'upload', type: 'user', text: `Uploaded tender: ${filename}` }])
    setActiveToolCall(null)
    setWatchingId(newJob.tender_id)
  }, [archiveCurrent])

  // SSE stream watcher
  useEffect(() => {
    if (!watchingId) return

    let lastStatus = null

    const es = openEventStream(
      watchingId,
      (data) => {
        if (data.error) {
          pushMessage({ type: 'error', text: String(data.error) })
          setActiveToolCall(null)
          setWatchingId(null)
          return
        }

        const status = data.status
        if (status === lastStatus) return
        lastStatus = status

        setJob(prev => prev ? { ...prev, ...data } : data)

        const toolMap = {
          analysing:  'analyse_tender',
          retrieving: 'retrieve_context',
          drafting:   'draft_sections',
          finalising: 'finalise',
        }
        if (toolMap[status]) setActiveToolCall(toolMap[status])

        // Add token estimates on key transitions
        if (status === 'drafting') {
          // We now know section count from job state or estimate 4
          const sectionCount = data.sections_json?.length ?? 4
          addTokenOps(buildPipelineEstimates(sectionCount))
        }
        if (status === 'finalising') {
          const sectionCount = data.sections_json?.length ?? 4
          addTokenOps(buildFinalisationEstimates(sectionCount))
        }

        const agentMessages = {
          analysing:       { type: 'agent', tool: 'analyse_tender',   heading: 'Analyse Tender',   text: 'Extracting sections, compliance checklist, and dimension weights...' },
          retrieving:      { type: 'agent', tool: 'retrieve_context', heading: 'Retrieve Context', text: 'Embedding queries and searching knowledge base for relevant chunks per section...' },
          drafting:        { type: 'agent', tool: 'draft_sections',   heading: 'Draft Sections',   text: 'Drafting response sections with Claude Sonnet. Running compliance & robustness scoring...' },
          finalising:      { type: 'agent', tool: 'finalise',         heading: 'Finalise',         text: 'Polishing the final document and generating DOCX output...' },
          awaiting_review: {
            type: 'agent-done', heading: 'Draft Complete — Review Required',
            text: `Tender response drafted. Final score: ${data.score_json?.final_score?.toFixed(1) ?? '—'}/100. Review and edit each section below.`,
            score: data.score_json,
          },
          done: {
            type: 'done', heading: 'Tender Response Complete',
            text: 'Your tender response has been generated and is ready to download.',
            tenderId: watchingId,
          },
          error: { type: 'error', text: data.error_msg || 'An error occurred.' },
        }

        if (agentMessages[status]) pushMessage(agentMessages[status])

        if (['awaiting_review', 'done', 'error'].includes(status)) {
          setActiveToolCall(null)
          setWatchingId(null)
        }
      },
      () => { setActiveToolCall(null); setWatchingId(null) }
    )

    esRef.current = es
    return () => { es.close(); esRef.current = null }
  }, [watchingId, pushMessage, addTokenOps])

  const handleReviewSubmit = useCallback((updatedJob) => {
    const tid = updatedJob.tender_id ?? job?.tender_id
    setJob(prev => ({ ...prev, ...updatedJob, tender_id: tid, status: 'finalising' }))
    setActiveToolCall('finalise')
    pushMessage({ type: 'user', text: 'Review submitted — finalising document...' })
    setWatchingId(tid)
  }, [pushMessage, job])

  const handleReset = useCallback(() => {
    archiveCurrent()           // snapshot before wiping
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    setJob(null)
    setMessages([])
    setActiveToolCall(null)
    setWatchingId(null)
    setTokenLog(emptyLog())
    setHistoryViewId(null)
  }, [archiveCurrent])

  // Auto-archive when job reaches a terminal pipeline state
  useEffect(() => {
    if (job?.status === 'awaiting_review' || job?.status === 'done' || job?.status === 'error') {
      archiveCurrent()
    }
  }, [job?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const historyItem = history.find(h => h.id === historyViewId) ?? null

  return (
    <div className="app-layout">
      <Sidebar
        currentJob={job}
        tokenLog={tokenLog}
        history={history}
        historyViewId={historyViewId}
        onSelectHistory={setHistoryViewId}
      />
      <div className="app-main">
        {historyItem ? (
          <ChatView
            job={historyItem.job}
            messages={historyItem.messages}
            activeToolCall={null}
            onReset={() => setHistoryViewId(null)}
            isHistoryView
          />
        ) : !job ? (
          <LandingView onJobStarted={handleJobStarted} />
        ) : job.status === 'awaiting_review' ? (
          <ReviewPanel
            job={job}
            onSubmit={handleReviewSubmit}
            onReset={handleReset}
            tokenLog={tokenLog}
            onTokensAdded={addTokenOps}
          />
        ) : (
          <ChatView
            job={job}
            messages={messages}
            activeToolCall={activeToolCall}
            onReset={handleReset}
          />
        )}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */

function LandingView({ onJobStarted }) {
  const [dragging,  setDragging]  = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error,     setError]     = useState(null)
  const inputRef = useRef(null)

  const handleFile = async (file) => {
    if (!file) return
    if (!file.name.match(/\.(pdf|txt|docx)$/i)) {
      setError('Please upload a PDF, TXT, or DOCX file.')
      return
    }
    setError(null)
    setUploading(true)
    try {
      const result = await startTender(file)
      onJobStarted(result, file.name)
    } catch (e) {
      setError(`Upload failed: ${e.message}`)
      setUploading(false)
    }
  }

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
}

function UploadIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  )
}

export function Spinner({ size = 20 }) {
  return (
    <svg className="spinner" width={size} height={size} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}
