// Token cost per million tokens (USD)
const MODEL_COST = {
  'claude-haiku-4-5-20251001': { input: 0.25,  output: 1.25  },
  'claude-sonnet-4-6':         { input: 3.00,  output: 15.00 },
  'claude-opus-4-6':           { input: 15.00, output: 75.00 },
}

export function estimateCost(model, inputTokens, outputTokens) {
  const c = MODEL_COST[model] ?? MODEL_COST['claude-sonnet-4-6']
  return (inputTokens * c.input + outputTokens * c.output) / 1_000_000
}

// Rough estimate: 1 token ≈ 4 chars
export function charsToTokens(str = '') {
  return Math.ceil(str.length / 4)
}

/**
 * Returns estimated token operations for a full pipeline run.
 * Call this once we know the section count (from awaiting_review data).
 */
export function buildPipelineEstimates(sectionCount = 4) {
  const n = Math.max(1, sectionCount)
  return [
    {
      op: 'analyse_tender',
      model: 'claude-haiku-4-5-20251001',
      input: 4200,
      output: 1600,
    },
    {
      op: 'retrieve_context',
      model: 'claude-haiku-4-5-20251001',
      input: 950,
      output: 30,
    },
    {
      // Sonnet per-section draft + Haiku quality scoring
      op: 'draft_sections',
      model: 'claude-sonnet-4-6',
      input: n * 2800 + 4500,
      output: n * 950,
    },
    {
      op: 'quality_scoring',
      model: 'claude-haiku-4-5-20251001',
      input: 5200,
      output: 50,
    },
  ]
}

export function buildFinalisationEstimates(sectionCount = 4) {
  const n = Math.max(1, sectionCount)
  return [
    {
      op: 'finalise',
      model: 'claude-sonnet-4-6',
      input: n * 1800,
      output: n * 720,
    },
  ]
}

/** Build a fresh token log object */
export function emptyLog() {
  return { ops: [], totalInput: 0, totalOutput: 0, totalCost: 0 }
}

/** Append one or more op entries to a log (immutable) */
export function addOps(log, ops) {
  const newOps = [...log.ops, ...ops.map(o => ({
    ...o,
    cost: estimateCost(o.model, o.input, o.output),
  }))]
  const totalInput  = newOps.reduce((s, o) => s + o.input, 0)
  const totalOutput = newOps.reduce((s, o) => s + o.output, 0)
  const totalCost   = newOps.reduce((s, o) => s + o.cost, 0)
  return { ops: newOps, totalInput, totalOutput, totalCost }
}
