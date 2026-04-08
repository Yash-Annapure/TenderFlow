import './ScoreCard.css'

const BAND_COLOR = {
  EXCELLENT: '#10a37f',
  STRONG:    '#6366f1',
  MODERATE:  '#f59e0b',
  WEAK:      '#ef4444',
}

function band(score) {
  if (score >= 90) return 'EXCELLENT'
  if (score >= 75) return 'STRONG'
  if (score >= 60) return 'MODERATE'
  return 'WEAK'
}

export default function ScoreCard({ score, compact = false }) {
  if (!score) return null

  const final = score.final_score ?? 0
  const primary = score.primary_score_total ?? 0
  const compliance = score.compliance_score ?? 0
  const robustness = score.robustness_score ?? 0
  const b = band(final)

  if (compact) {
    return (
      <div className="score-compact">
        <div className="score-compact-main">
          <span className="score-big" style={{ color: BAND_COLOR[b] }}>
            {final.toFixed(1)}
          </span>
          <span className="score-slash">/100</span>
          <span className="score-band-pill" style={{ background: BAND_COLOR[b] + '22', color: BAND_COLOR[b] }}>
            {b}
          </span>
        </div>
        <div className="score-bars">
          <ScoreBar label="Primary" value={primary} color="#6366f1" />
          <ScoreBar label="Compliance" value={compliance} color="#10a37f" />
          <ScoreBar label="Robustness" value={robustness} color="#0ea5e9" />
        </div>
      </div>
    )
  }

  return (
    <div className="score-card">
      <div className="score-card-header">
        <div className="score-card-label-row">
          <span className="score-card-label">Response Score</span>
          <span className="score-band-pill" style={{ background: BAND_COLOR[b] + '22', color: BAND_COLOR[b] }}>{b}</span>
        </div>
        <div className="score-card-value-row">
          <span className="score-big" style={{ color: BAND_COLOR[b] }}>{final.toFixed(1)}</span>
          <span className="score-slash">/100</span>
        </div>
      </div>

      <div className="score-grid">
        <ScoreBar label="Primary Score" value={primary} color="#6366f1" />
        <ScoreBar label="Compliance Coverage" value={compliance} color="#10a37f" />
        <ScoreBar label="Robustness Index" value={robustness} color="#0ea5e9" />
      </div>

      {score.score_justifications && Object.keys(score.score_justifications).length > 0 && (
        <div className="score-justifications">
          {Object.entries(score.score_justifications).map(([k, v]) => (
            <div key={k} className="justification-row">
              <span className="justification-key">{k}</span>
              <span className="justification-val">{v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ScoreBar({ label, value, color }) {
  const pct = Math.min(Math.max(value, 0), 100)
  return (
    <div className="score-bar-row">
      <div className="score-bar-meta">
        <span className="score-bar-label">{label}</span>
        <span className="score-bar-value">{pct.toFixed(1)}</span>
      </div>
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  )
}
