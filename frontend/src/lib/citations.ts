export type AnswerPart = { kind: 'text'; text: string } | { kind: 'cite'; n: number }

/** Split an answer into text and [n] / [n, m] citation markers. */
export function splitCitations(answer: string): AnswerPart[] {
  const parts: AnswerPart[] = []
  const re = /\[(\d+(?:\s*,\s*\d+)*)\]/g
  let last = 0
  for (const m of answer.matchAll(re)) {
    if (m.index > last) parts.push({ kind: 'text', text: answer.slice(last, m.index) })
    for (const n of m[1].split(',')) parts.push({ kind: 'cite', n: Number(n.trim()) })
    last = m.index + m[0].length
  }
  if (last < answer.length) parts.push({ kind: 'text', text: answer.slice(last) })
  return parts
}
