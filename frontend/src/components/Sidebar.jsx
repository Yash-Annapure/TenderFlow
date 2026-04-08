import { useState, useEffect, useRef } from 'react'
import { listKBDocuments, ingestDocument, pollIngestStatus } from '../api/client.js'
import './Sidebar.css'

const DOC_TYPE_LABELS = {
  past_tender:     'Past Tender',
  cv:              'CV',
  methodology:     'Methodology',
  company_profile: 'Company Profile',
}

const DOC_TYPE_COLORS = {
  past_tender:     '#6366f1',
  cv:              '#0ea5e9',
  methodology:     '#10a37f',
  company_profile: '#f59e0b',
}

export default function Sidebar({ currentJob }) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const pollRef = useRef(null)

  const fetchDocs = async () => {
    try {
      const data = await listKBDocuments()
      setDocs(data.documents || [])
    } catch {
      // silent fail
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs()
    const interval = setInterval(fetchDocs, 10000)
    return () => clearInterval(interval)
  }, [])

  const handleIngest = async (file, docType, sourceName) => {
    setUploading(true)
    setUploadError(null)
    try {
      const task = await ingestDocument(file, docType, sourceName)
      // Poll for completion
      await new Promise((resolve, reject) => {
        const timer = setInterval(async () => {
          try {
            const status = await pollIngestStatus(task.task_id)
            if (status.status !== 'running') {
              clearInterval(timer)
              if (status.status === 'error') reject(new Error(status.error || 'Ingest failed'))
              else resolve(status)
            }
          } catch (e) { clearInterval(timer); reject(e) }
        }, 2000)
        pollRef.current = timer
      })
      await fetchDocs()
      setShowModal(false)
    } catch (e) {
      setUploadError(e.message)
    } finally {
      setUploading(false)
    }
  }

  const grouped = docs.reduce((acc, doc) => {
    const t = doc.doc_type || 'unknown'
    if (!acc[t]) acc[t] = []
    acc[t].push(doc)
    return acc
  }, {})

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <span className="sidebar-logo-mark">TF</span>
          <span className="sidebar-logo-name">TenderFlow</span>
        </div>
      </div>

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
              {items.map(doc => (
                <div key={doc.id} className="kb-doc">
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

      <div className="sidebar-footer">
        <button className="sidebar-add-btn" onClick={() => setShowModal(true)}>
          <PlusIcon />
          Add Document
        </button>
      </div>

      {currentJob && (
        <div className="sidebar-job">
          <div className="sidebar-section-title" style={{ marginBottom: 8 }}>Active Job</div>
          <div className="job-card">
            <div className="job-filename">{currentJob.tender_filename || 'tender.pdf'}</div>
            <div className={`job-status job-status--${currentJob.status}`}>
              {currentJob.status}
            </div>
            {currentJob.score_json?.final_score != null && (
              <div className="job-score">
                Score: <strong>{currentJob.score_json.final_score.toFixed(1)}</strong>/100
              </div>
            )}
          </div>
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
  )
}

function IngestModal({ onClose, onSubmit, uploading, error }) {
  const [file, setFile] = useState(null)
  const [docType, setDocType] = useState('past_tender')
  const [sourceName, setSourceName] = useState('')
  const inputRef = useRef(null)

  const submit = () => {
    if (!file || !sourceName.trim()) return
    onSubmit(file, docType, sourceName.trim())
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>Add KB Document</span>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <label className="modal-label">Document Type</label>
          <select className="modal-select" value={docType} onChange={e => setDocType(e.target.value)}>
            {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>

          <label className="modal-label">Source Name</label>
          <input
            className="modal-input"
            placeholder="e.g. Company Profile 2024"
            value={sourceName}
            onChange={e => setSourceName(e.target.value)}
          />

          <label className="modal-label">File</label>
          <div
            className="modal-file"
            onClick={() => inputRef.current?.click()}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.txt,.docx"
              style={{ display: 'none' }}
              onChange={e => setFile(e.target.files[0])}
            />
            {file ? (
              <span className="modal-file-name">{file.name}</span>
            ) : (
              <span className="modal-file-placeholder">Click to select file</span>
            )}
          </div>

          {error && <div className="modal-error">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="modal-cancel" onClick={onClose} disabled={uploading}>Cancel</button>
          <button
            className="modal-submit"
            onClick={submit}
            disabled={uploading || !file || !sourceName.trim()}
          >
            {uploading ? 'Uploading...' : 'Upload & Ingest'}
          </button>
        </div>
      </div>
    </div>
  )
}

function DocIcon({ type }) {
  const color = DOC_TYPE_COLORS[type] || '#8e8ea0'
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" style={{ flexShrink: 0 }}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function StatusDot({ status }) {
  const color = status === 'active' ? '#10a37f' : status === 'processing' ? '#f59e0b' : '#8e8ea0'
  return <div className="status-dot" style={{ background: color }} title={status} />
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}
