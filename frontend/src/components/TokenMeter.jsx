import './TokenMeter.css'

const MODEL_LABELS = {
  'claude-haiku-4-5-20251001': 'Haiku',
  'claude-sonnet-4-6':         'Sonnet',
  'claude-opus-4-6':           'Opus',
}

const BUDGET_TOKENS = 200_000  // soft budget for the meter fill

function fmt(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function fmtCost(usd) {
  if (usd < 0.001) return '<$0.001'
  if (usd < 1)     return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(3)}`
}

export default function TokenMeter({ tokenLog }) {
  if (!tokenLog || tokenLog.ops.length === 0) return null

  const { ops, totalInput, totalOutput, totalCost } = tokenLog
  const totalTokens = totalInput + totalOutput
  const pct = Math.min((totalTokens / BUDGET_TOKENS) * 100, 100)

  const meterColor = pct > 80 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#10a37f'

  return (
    <div className="token-meter">
      <div className="token-meter-header">
        <span className="token-meter-title">Token Usage</span>
        <span className="token-meter-cost" title="Estimated API cost">{fmtCost(totalCost)}</span>
      </div>

      <div className="token-meter-bar-track">
        <div
          className="token-meter-bar-fill"
          style={{ width: `${pct}%`, background: meterColor }}
        />
      </div>

      <div className="token-meter-totals">
        <span title="Total tokens consumed">{fmt(totalTokens)} tok</span>
        <span className="token-meter-split">
          <span className="token-in" title="Input tokens">↑{fmt(totalInput)}</span>
          <span className="token-out" title="Output tokens">↓{fmt(totalOutput)}</span>
        </span>
      </div>

      <div className="token-meter-ops">
        {ops.map((op, i) => (
          <div key={i} className="token-op-row">
            <span className="token-op-name">{op.op}</span>
            <span className="token-op-model">{MODEL_LABELS[op.model] ?? op.model}</span>
            <span className="token-op-tokens">{fmt(op.input + op.output)}</span>
            <span className="token-op-cost">{fmtCost(op.cost)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
