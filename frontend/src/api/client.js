const BASE = ''  // proxied via vite dev server

export async function startTender(file) {
  const form = new FormData()
  form.append('file', file)
  form.append('output_format', 'docx')
  const res = await fetch(`${BASE}/tender/start`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getTenderStatus(tenderId) {
  const res = await fetch(`${BASE}/tender/${tenderId}/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getReview(tenderId) {
  const res = await fetch(`${BASE}/tender/${tenderId}/review`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitReview(tenderId, { sections, feedback, requestAnotherRound }) {
  const res = await fetch(`${BASE}/tender/${tenderId}/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sections: sections.map(s => ({
        section_id: s.section_id,
        user_edits: s.user_edits ?? null,
      })),
      feedback: feedback ?? '',
      request_another_round: requestAnotherRound ?? false,
    }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function openEventStream(tenderId, onEvent, onEnd) {
  const es = new EventSource(`${BASE}/tender/${tenderId}/events`)
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      onEvent(data)
      if (['awaiting_review', 'done', 'error'].includes(data.status)) {
        es.close()
        onEnd && onEnd(data)
      }
    } catch {}
  }
  es.onerror = () => { es.close(); onEnd && onEnd(null) }
  return es
}

export async function listKBDocuments() {
  const res = await fetch(`${BASE}/kb/documents`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function ingestDocument(file, docType, sourceName) {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  form.append('source_name', sourceName)
  form.append('uploaded_by', 'ui')
  const res = await fetch(`${BASE}/ingest/document`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function pollIngestStatus(taskId) {
  const res = await fetch(`${BASE}/ingest/status/${taskId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * Re-iterate a single section via the backend's /tender/reiterate-section endpoint.
 * Uses the backend's already-configured Anthropic client (Haiku, token-optimised).
 * Returns { text, inputTokens, outputTokens }
 */
export async function reiterateSection({ sectionName, requirements, currentDraft, instruction, wordTarget = 500 }) {
  const res = await fetch('/tender/reiterate-section', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      section_name:  sectionName,
      requirements:  requirements,
      current_draft: currentDraft,
      instruction:   instruction,
      word_target:   wordTarget,
    }),
  })

  if (!res.ok) throw new Error(await res.text())

  const data = await res.json()
  return {
    text:         data.text,
    inputTokens:  data.input_tokens,
    outputTokens: data.output_tokens,
  }
}
