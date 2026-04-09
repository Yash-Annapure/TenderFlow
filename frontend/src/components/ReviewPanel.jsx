import { useState, useEffect, useRef, useCallback } from 'react'
import { getReview, submitReview, reiterateSection } from '../api/client.js'
import ScoreCard from './ScoreCard'
import DocxPreview from './DocxPreview'
import './ReviewPanel.css'

const CONFIDENCE_COLOR = { HIGH: '#10a37f', MEDIUM: '#f59e0b', LOW: '#ef4444' }

export default function ReviewPanel({ job, onSubmit, onReset, onTokensAdded, isHistoryView = false }) {
  const [review,        setReview]        = useState(null)
  const [sections,      setSections]      = useState([])
  const [feedback,      setFeedback]      = useState('')
  const [anotherRound,  setAnotherRound]  = useState(false)
  const [loading,       setLoading]       = useState(true)
  const [submitting,    setSubmitting]     = useState(false)
  const [error,         setError]         = useState(null)
  const [activeIdx,     setActiveIdx]     = useState(0)
  const [viewMode,      setViewMode]      = useState('split')  // 'edit' | 'split' | 'preview'
  const previewRef = useRef(null)

  useEffect(() => {
    getReview(job.tender_id)
      .then(data => {
        setReview(data)
        setSections(
          (data.sections || []).map(s => ({
            ...s,
            user_edits: s.user_edits || s.finalised_content || s.draft_text || '',
          }))
        )
        setLoading(false)
      })
      .catch(() => {
        // Fallback: use sections already on the job object (history / done views)
        const fallbackSections = job.sections_json || job.sections || []
        setSections(
          fallbackSections.map(s => ({
            ...s,
            user_edits: s.user_edits || s.finalised_content || s.draft_text || '',
          }))
        )
        setLoading(false)
      })
  }, [job.tender_id])

  // Scroll preview to active section
  useEffect(() => {
    if (viewMode !== 'edit' && sections[activeIdx]) {
      const el = previewRef.current?.querySelector(`#preview-${sections[activeIdx].section_id}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [activeIdx, viewMode, sections])

  const handleEdit = useCallback((idx, value) => {
    setSections(prev => prev.map((s, i) => i === idx ? { ...s, user_edits: value } : s))
  }, [])

  const handleRename = useCallback((idx, name) => {
    setSections(prev => prev.map((s, i) => i === idx ? { ...s, section_name: name } : s))
  }, [])

  const handleReiterate = useCallback(async (idx, instruction, appendMode = false) => {
    const s = sections[idx]
    // Strip DRAFT ERROR markers so the model gets clean context
    const cleanDraft = (s.user_edits || s.draft_text || '').replace(/\[DRAFT ERROR[^\]]*\]/g, '').trim()
    const result = await reiterateSection({
      sectionName:   s.section_name,
      requirements:  s.requirements,
      currentDraft:  cleanDraft,
      instruction,
      wordTarget:    s.word_count_target || 500,
    })
    setSections(prev => prev.map((sec, i) => {
      if (i !== idx) return sec
      const newText = appendMode && cleanDraft
        ? cleanDraft + '\n\n' + result.text
        : result.text
      return { ...sec, user_edits: newText }
    }))
    onTokensAdded?.([{
      op:     `reiterate:${s.section_id}`,
      model:  'claude-haiku-4-5-20251001',
      input:  result.inputTokens,
      output: result.outputTokens,
    }])
  }, [sections, onTokensAdded])

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const result = await submitReview(job.tender_id, { sections, feedback, requestAnotherRound: anotherRound })
      onSubmit({ ...result, tender_id: job.tender_id })
    } catch (e) {
      setError(typeof e.message === 'string' ? e.message : JSON.stringify(e.message))
      setSubmitting(false)
    }
  }

  const scoreJson = review
    ? {
        final_score: review.final_score,
        score_justifications: review.score_justifications,
        primary_score_total: job?.score_json?.primary_score_total,
        compliance_score:    job?.score_json?.compliance_score,
        robustness_score:    job?.score_json?.robustness_score,
      }
    : job?.score_json

  if (loading) {
    return (
      <div className="review-loading">
        <div className="review-spinner" />
        <span>Loading draft...</span>
      </div>
    )
  }

  const activeSectionId = sections[activeIdx]?.section_id ?? null

  return (
    <div className="review-layout">
      {/* ── Left panel ── */}
      <div className="review-left">
        <div className="review-left-header">
          <div className="review-left-title">
            {isHistoryView
              ? <span className="review-badge review-badge--history">History</span>
              : <span className="review-badge">Review</span>
            }
            <span className="review-iteration">Round {(review?.hitl_iteration ?? 0) + 1}</span>
          </div>
          <button className="review-reset-btn" onClick={onReset}>
            {isHistoryView ? '← Back' : '← New'}
          </button>
        </div>

        {scoreJson && <ScoreCard score={scoreJson} />}

        <div className="review-section-nav">
          {sections.map((s, i) => (
            <button
              key={s.section_id}
              className={`review-nav-item ${i === activeIdx ? 'review-nav-item--active' : ''}`}
              onClick={() => setActiveIdx(i)}
            >
              <span className="review-nav-name">{s.section_name}</span>
              <ConfidenceDot confidence={s.confidence} />
            </button>
          ))}
          {!isHistoryView && (
            <button
              className="review-nav-add-btn"
              onClick={() => {
                const newId = `custom_${Date.now()}`
                const newSection = {
                  section_id: newId,
                  section_name: 'New Section',
                  user_edits: '',
                  draft_text: '',
                  requirements: [],
                  sources_used: [],
                  confidence: 'MEDIUM',
                  gap_flag: null,
                  word_count_target: 400,
                  isNew: true,
                }
                setSections(prev => [...prev, newSection])
                setActiveIdx(sections.length)
              }}
            >
              + Add Section
            </button>
          )}
        </div>

      </div>

      {/* ── Right panel ── */}
      <div className="review-right">
        {/* Top bar with view toggle */}
        <div className="review-topbar">
          <div className="review-topbar-left">
            <span className="review-section-title">{sections[activeIdx]?.section_name || ''}</span>
            {sections[activeIdx] && <ConfidenceBadge confidence={sections[activeIdx].confidence} />}
          </div>
          <div className="view-toggle">
            <div
              className="view-toggle-pill"
              style={{ transform: `translateX(${viewMode === 'edit' ? '0%' : viewMode === 'split' ? '100%' : '200%'})` }}
            />
            <button className={`view-toggle-btn ${viewMode === 'edit' ? 'active' : ''}`}    onClick={() => setViewMode('edit')}>Edit</button>
            <button className={`view-toggle-btn ${viewMode === 'split' ? 'active' : ''}`}   onClick={() => setViewMode('split')}>Split</button>
            <button className={`view-toggle-btn ${viewMode === 'preview' ? 'active' : ''}`} onClick={() => setViewMode('preview')}>Preview</button>
          </div>
          {job?.status === 'done' && (
            <>
              <a
                href={`/tender/${job.tender_id}/download`}
                className="review-download-btn"
                download
              >
                <DownloadIcon />
                Download DOCX
              </a>
              <button
                className="review-download-btn review-download-btn--pdf"
                onClick={() => {
                  const prev = viewMode
                  setViewMode('preview')
                  setTimeout(() => { window.print(); setViewMode(prev) }, 120)
                }}
              >
                <PdfIcon />
                Download PDF
              </button>
            </>
          )}
          {(!isHistoryView || job?.status === 'done') && (
            <button className="review-submit-topbar-btn" onClick={handleSubmit} disabled={submitting}>
              {submitting ? 'Submitting…' : anotherRound ? 'Submit & Revise' : job?.status === 'done' ? 'Re-finalise' : 'Submit & Finalise'}
            </button>
          )}
        </div>

        {/* Main content area */}
        <div className={`review-content review-content--${viewMode}`}>
          {/* Edit pane */}
          {viewMode !== 'preview' && (
            <div className="review-edit-pane">
              {sections.length > 0 && (
                <SectionEditor
                  key={sections[activeIdx]?.section_id}
                  section={sections[activeIdx]}
                  index={activeIdx}
                  total={sections.length}
                  tenderId={job?.tender_id}
                  jobStatus={job?.status}
                  isHistoryView={isHistoryView}
                  onEdit={(v) => handleEdit(activeIdx, v)}
                  onRename={(name) => handleRename(activeIdx, name)}
                  onReiterate={(inst, appendMode) => handleReiterate(activeIdx, inst, appendMode)}
                  onPrev={() => setActiveIdx(i => Math.max(0, i - 1))}
                  onNext={() => setActiveIdx(i => Math.min(sections.length - 1, i + 1))}
                />
              )}

              {/* Final submit area at end of last section */}
              {activeIdx === sections.length - 1 && (
                <div className="review-submit-area">
                  <div className="review-feedback-label">Overall feedback (optional)</div>
                  <textarea
                    className="review-feedback-input"
                    placeholder="Any notes for the agent on this revision..."
                    value={feedback}
                    onChange={e => setFeedback(e.target.value)}
                    rows={3}
                  />
                  <label className="review-another-round">
                    <input type="checkbox" checked={anotherRound} onChange={e => setAnotherRound(e.target.checked)} />
                    Request another AI revision round after finalising
                  </label>
                  {error && <div className="review-error">{error}</div>}
                  <div className="review-actions">
                    <button className="review-submit-btn" onClick={handleSubmit} disabled={submitting}>
                      {submitting ? 'Submitting…' : anotherRound ? 'Submit & Request Revision' : 'Submit & Finalise'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Preview pane */}
          {viewMode !== 'edit' && (
            <div className="review-preview-pane" ref={previewRef}>
              <DocxPreview
                sections={sections}
                filename={job.tender_filename}
                activeSectionId={activeSectionId}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */

function SectionEditor({ section, index, total, tenderId, jobStatus, isHistoryView, onEdit, onRename, onReiterate, onPrev, onNext }) {
  const [reiterateOpen,  setReiterateOpen]  = useState(false)
  const [instruction,    setInstruction]    = useState('')
  const [appendMode,     setAppendMode]     = useState(false)
  const [reiterating,    setReiterating]    = useState(false)
  const [reiterateError, setReiterateError] = useState(null)

  const handleReiterate = async () => {
    if (!instruction.trim()) return
    setReiterating(true)
    setReiterateError(null)
    try {
      await onReiterate(instruction.trim(), appendMode)
      setInstruction('')
      setReiterateOpen(false)
    } catch (e) {
      setReiterateError(e.message)
    } finally {
      setReiterating(false)
    }
  }

  return (
    <div className="section-editor">
      {/* Requirements */}
      {section.requirements?.length > 0 && (
        <div className="section-requirements">
          <div className="section-req-title">Requirements</div>
          <ul className="section-req-list">
            {section.requirements.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Gap flag */}
      {section.gap_flag && (
        <div className="section-gap">⚠ {section.gap_flag}</div>
      )}

      {/* Sources */}
      {section.sources_used?.length > 0 && (
        <div className="section-sources">
          <span className="section-sources-label">Sources:</span>
          {section.sources_used.map((s, i) => <span key={i} className="section-source-tag">{s}</span>)}
        </div>
      )}

      {/* Editable name for new sections */}
      {section.isNew && (
        <input
          className="section-name-input"
          value={section.section_name}
          onChange={e => onRename(e.target.value)}
          placeholder="Section name…"
        />
      )}

      {/* Draft textarea */}
      <div className="section-editor-label">
        Draft
        <span className="section-word-count">
          {Math.round((section.user_edits || '').split(/\s+/).filter(Boolean).length)} words
        </span>
      </div>
      <textarea
        className="section-draft-textarea"
        value={section.user_edits ?? section.draft_text ?? ''}
        onChange={e => onEdit(e.target.value)}
        placeholder={section.isNew ? 'Write your new section here, or use Re-iterate with AI…' : 'Draft will appear here…'}
      />

      {/* ── Re-iterate button ── */}
      <div className="reiterate-wrap">
        <button
          className={`reiterate-toggle-btn ${reiterateOpen ? 'active' : ''}`}
          onClick={() => { setReiterateOpen(v => !v); setReiterateError(null) }}
        >
          <ReiterateIcon />
          Re-iterate with AI
        </button>

        {reiterateOpen && (
          <div className="reiterate-panel">
            <div className="reiterate-hint">
              Haiku will revise this section only. Be specific — fewer tokens, better results.
            </div>
            <textarea
              className="reiterate-input"
              placeholder='e.g. "Make the opening paragraph more concise and add a specific metric"'
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
              rows={2}
              onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleReiterate() }}
            />
            {reiterateError && <div className="reiterate-error">{reiterateError}</div>}
            <div className="reiterate-actions">
              <label className="reiterate-append-toggle" title="Append AI output after existing text instead of replacing it">
                <input type="checkbox" checked={appendMode} onChange={e => setAppendMode(e.target.checked)} />
                Append
              </label>
              <span className="reiterate-model-badge">claude-haiku-4-5 · ⌘↵</span>
              <button
                className="reiterate-submit-btn"
                onClick={handleReiterate}
                disabled={reiterating || !instruction.trim()}
              >
                {reiterating ? (
                  <><RingSpinner /> Rewriting…</>
                ) : appendMode ? 'Add to Section' : 'Revise Section'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Nav + download */}
      <div className="section-nav-btns">
        <button className="section-nav-btn" onClick={onPrev} disabled={index === 0}>← Prev</button>
        <span className="section-nav-counter">{index + 1} / {total}</span>
        <button className="section-nav-btn section-nav-btn--primary" onClick={onNext} disabled={index === total - 1}>Next →</button>
        {jobStatus === 'done' && tenderId && (
          <a
            href={`/tender/${tenderId}/download`}
            className="section-download-btn"
            download
            title="Download DOCX"
          >
            <DownloadIcon />
          </a>
        )}
      </div>
    </div>
  )
}

function ConfidenceDot({ confidence }) {
  return <div className="conf-dot" style={{ background: CONFIDENCE_COLOR[confidence] || '#8e8ea0' }} title={confidence} />
}

function ConfidenceBadge({ confidence }) {
  const color = CONFIDENCE_COLOR[confidence] || '#8e8ea0'
  if (!confidence) return null
  return <span className="conf-badge" style={{ color, background: color + '22', borderColor: color + '44' }}>{confidence}</span>
}

function ReiterateIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
      <polyline points="1 4 1 10 7 10" />
      <path d="M3.51 15a9 9 0 1 0 .49-4.92" />
    </svg>
  )
}

function RingSpinner() {
  return (
    <svg className="spinner" width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ display: 'inline-block' }}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
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

function PdfIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="9" y1="13" x2="15" y2="13" />
      <line x1="9" y1="17" x2="12" y2="17" />
    </svg>
  )
}
