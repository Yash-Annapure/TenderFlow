import { useState, useEffect, useRef } from 'react'
import { getReview, submitReview } from '../api/client.js'
import ScoreCard from './ScoreCard'
import './ReviewPanel.css'

const CONFIDENCE_COLOR = { HIGH: '#10a37f', MEDIUM: '#f59e0b', LOW: '#ef4444' }

export default function ReviewPanel({ job, messages, onSubmit, onReset }) {
  const [review, setReview] = useState(null)
  const [sections, setSections] = useState([])
  const [feedback, setFeedback] = useState('')
  const [anotherRound, setAnotherRound] = useState(false)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [activeSection, setActiveSection] = useState(0)
  const scrollRef = useRef(null)

  useEffect(() => {
    getReview(job.tender_id)
      .then(data => {
        setReview(data)
        setSections(
          (data.sections || []).map(s => ({ ...s, user_edits: s.user_edits || s.draft_text || '' }))
        )
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [job.tender_id])

  const handleSectionEdit = (idx, value) => {
    setSections(prev => prev.map((s, i) => i === idx ? { ...s, user_edits: value } : s))
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const result = await submitReview(job.tender_id, {
        sections,
        feedback,
        requestAnotherRound: anotherRound,
      })
      onSubmit(result)
    } catch (e) {
      setError(e.message)
      setSubmitting(false)
    }
  }

  const scoreJson = review
    ? {
        final_score: review.final_score,
        score_justifications: review.score_justifications,
        primary_score_total: job?.score_json?.primary_score_total,
        compliance_score: job?.score_json?.compliance_score,
        robustness_score: job?.score_json?.robustness_score,
      }
    : job?.score_json

  if (loading) {
    return (
      <div className="review-loading">
        <div className="review-spinner" />
        <span>Loading review...</span>
      </div>
    )
  }

  return (
    <div className="review-layout">
      {/* Left: section list + score */}
      <div className="review-left">
        <div className="review-left-header">
          <div className="review-left-title">
            <span className="review-badge">HITL Review</span>
            <span className="review-iteration">Round {(review?.hitl_iteration ?? 0) + 1}</span>
          </div>
          <button className="review-reset-btn" onClick={onReset}>← New Tender</button>
        </div>

        {scoreJson && <ScoreCard score={scoreJson} />}

        <div className="review-section-nav">
          {sections.map((s, i) => (
            <button
              key={s.section_id}
              className={`review-nav-item ${i === activeSection ? 'review-nav-item--active' : ''}`}
              onClick={() => setActiveSection(i)}
            >
              <span className="review-nav-name">{s.section_name}</span>
              <ConfidenceDot confidence={s.confidence} />
            </button>
          ))}
        </div>
      </div>

      {/* Right: editor */}
      <div className="review-right" ref={scrollRef}>
        {sections.length === 0 ? (
          <div className="review-empty">No sections to review.</div>
        ) : (
          <SectionEditor
            key={sections[activeSection]?.section_id}
            section={sections[activeSection]}
            index={activeSection}
            total={sections.length}
            onEdit={(val) => handleSectionEdit(activeSection, val)}
            onPrev={() => setActiveSection(i => Math.max(0, i - 1))}
            onNext={() => setActiveSection(i => Math.min(sections.length - 1, i + 1))}
          />
        )}

        {activeSection === sections.length - 1 && (
          <div className="review-submit-area">
            <div className="review-feedback-label">General Feedback (optional)</div>
            <textarea
              className="review-feedback-input"
              placeholder="Any overall notes for the next revision..."
              value={feedback}
              onChange={e => setFeedback(e.target.value)}
              rows={3}
            />

            <label className="review-another-round">
              <input
                type="checkbox"
                checked={anotherRound}
                onChange={e => setAnotherRound(e.target.checked)}
              />
              Request another revision round after finalise
            </label>

            {error && <div className="review-error">{error}</div>}

            <div className="review-actions">
              <button
                className="review-submit-btn"
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : anotherRound ? 'Submit & Request Revision' : 'Submit & Finalise'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function SectionEditor({ section, index, total, onEdit, onPrev, onNext }) {
  return (
    <div className="section-editor">
      <div className="section-editor-header">
        <div className="section-editor-meta">
          <span className="section-number">{index + 1} / {total}</span>
          <h2 className="section-name">{section.section_name}</h2>
          <ConfidenceBadge confidence={section.confidence} />
          {section.gap_flag && (
            <div className="section-gap">⚠ {section.gap_flag}</div>
          )}
        </div>
      </div>

      {section.requirements?.length > 0 && (
        <div className="section-requirements">
          <div className="section-req-title">Requirements</div>
          <ul className="section-req-list">
            {section.requirements.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {section.sources_used?.length > 0 && (
        <div className="section-sources">
          <span className="section-sources-label">Sources:</span>
          {section.sources_used.map((s, i) => (
            <span key={i} className="section-source-tag">{s}</span>
          ))}
        </div>
      )}

      <div className="section-editor-label">Draft (editable)</div>
      <textarea
        className="section-draft-textarea"
        value={section.user_edits ?? section.draft_text ?? ''}
        onChange={e => onEdit(e.target.value)}
        rows={18}
        placeholder="Draft will appear here..."
      />

      <div className="section-nav-btns">
        <button
          className="section-nav-btn"
          onClick={onPrev}
          disabled={index === 0}
        >
          ← Previous
        </button>
        <button
          className="section-nav-btn section-nav-btn--primary"
          onClick={onNext}
          disabled={index === total - 1}
        >
          Next →
        </button>
      </div>
    </div>
  )
}

function ConfidenceDot({ confidence }) {
  const color = CONFIDENCE_COLOR[confidence] || '#8e8ea0'
  return <div className="conf-dot" style={{ background: color }} title={confidence} />
}

function ConfidenceBadge({ confidence }) {
  const color = CONFIDENCE_COLOR[confidence] || '#8e8ea0'
  if (!confidence) return null
  return (
    <span className="conf-badge" style={{ color, background: color + '22', borderColor: color + '44' }}>
      {confidence}
    </span>
  )
}
