/**
 * Lightweight text → HTML converter for tender draft sections.
 * Handles: headings, bold/italic, bullet lists, numbered lists,
 * markdown tables, and paragraph blocks.
 */

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function inlineFormat(str) {
  return escHtml(str)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,     '<em>$1</em>')
    .replace(/`(.+?)`/g,       '<code>$1</code>')
}

function isTableRow(line) {
  return /^\s*\|.+\|\s*$/.test(line)
}

function isSeparatorRow(line) {
  return /^\s*\|[\s\-:|]+\|\s*$/.test(line)
}

function parseTableBlock(lines) {
  const rows = lines.filter(l => !isSeparatorRow(l))
  if (rows.length === 0) return ''

  const cells = (row) =>
    row.split('|').slice(1, -1).map(c => inlineFormat(c.trim()))

  const [header, ...body] = rows
  const headerCells = cells(header).map(c => `<th>${c}</th>`).join('')
  const bodyRows = body.map(r =>
    `<tr>${cells(r).map(c => `<td>${c}</td>`).join('')}</tr>`
  ).join('')

  return `<table><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table>`
}

export function textToHtml(text = '') {
  if (!text.trim()) return '<p class="empty-section">No draft content yet.</p>'

  const lines = text.split('\n')
  const out = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Heading
    const h3 = trimmed.match(/^###\s+(.+)/)
    const h2 = trimmed.match(/^##\s+(.+)/)
    const h1 = trimmed.match(/^#\s+(.+)/)
    if (h3) { out.push(`<h3>${inlineFormat(h3[1])}</h3>`); i++; continue }
    if (h2) { out.push(`<h2>${inlineFormat(h2[1])}</h2>`); i++; continue }
    if (h1) { out.push(`<h1>${inlineFormat(h1[1])}</h1>`); i++; continue }

    // Table block
    if (isTableRow(trimmed)) {
      const block = []
      while (i < lines.length && isTableRow(lines[i].trim())) {
        block.push(lines[i].trim())
        i++
      }
      out.push(parseTableBlock(block))
      continue
    }

    // Bullet list
    if (/^[-•*]\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^[-•*]\s+/.test(lines[i].trim())) {
        items.push(`<li>${inlineFormat(lines[i].trim().replace(/^[-•*]\s+/, ''))}</li>`)
        i++
      }
      out.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    // Numbered list
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i].trim())) {
        items.push(`<li>${inlineFormat(lines[i].trim().replace(/^\d+[.)]\s+/, ''))}</li>`)
        i++
      }
      out.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    // Empty line — skip (paragraph spacing handled by CSS)
    if (!trimmed) { i++; continue }

    // Regular paragraph — accumulate consecutive non-empty lines.
    // Stop only at lines that are actually headings, bullets, or numbered-list items —
    // NOT at bare digit-starting lines like "2023 revenue" or "4.2% growth".
    const paraLines = []
    while (i < lines.length) {
      const pl = lines[i].trim()
      if (!pl) break                          // empty line → end paragraph
      if (isTableRow(pl)) break              // table row
      if (/^#{1,3}\s/.test(pl)) break        // heading
      if (/^[-•*]\s/.test(pl)) break         // bullet
      if (/^\d+[.)]\s/.test(pl)) break       // numbered list item
      paraLines.push(inlineFormat(pl))
      i++
    }
    if (paraLines.length) out.push(`<p>${paraLines.join(' ')}</p>`)
  }

  return out.join('') || '<p class="empty-section">No draft content yet.</p>'
}
