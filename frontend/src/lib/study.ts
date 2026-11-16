import type { Card, Rating } from '../types/graph'

/** "10m", "3d", "2.5mo", "1.2y": compact interval labels for the rating buttons. */
export function formatInterval(seconds: number): string {
  const m = seconds / 60
  if (m < 60) return `${Math.max(1, Math.round(m))}m`
  const h = m / 60
  if (h < 24) return `${Math.round(h)}h`
  const d = h / 24
  if (d < 30) return `${Math.round(d)}d`
  if (d < 365) return `${trim(d / 30)}mo`
  return `${trim(d / 365)}y`
}

function trim(x: number): string {
  return x < 10 ? x.toFixed(1).replace(/\.0$/, '') : String(Math.round(x))
}

export const RATINGS: { value: Rating; label: string; key: string }[] = [
  { value: 1, label: 'Again', key: '1' },
  { value: 2, label: 'Hard', key: '2' },
  { value: 3, label: 'Good', key: '3' },
  { value: 4, label: 'Easy', key: '4' },
]

// ── Session state ─────────────────────────────────────────────────────────────

export interface SessionState {
  status: 'loading' | 'studying' | 'finished' | 'error'
  queue: Card[]
  revealed: boolean
  reviewed: number
  counts: Record<Rating, number>
  error: string | null
}

export const initialSession: SessionState = {
  status: 'loading', queue: [], revealed: false, reviewed: 0, counts: { 1: 0, 2: 0, 3: 0, 4: 0 }, error: null,
}

export type SessionAction =
  | { type: 'loaded'; cards: Card[] }
  | { type: 'reveal' }
  | { type: 'rated'; rating: Rating; card: Card }
  | { type: 'failed'; message: string }

/** Cards rated Again come back at the end of this session (they're due again in minutes). */
export function sessionReducer(s: SessionState, a: SessionAction): SessionState {
  switch (a.type) {
    case 'loaded':
      return { ...initialSession, status: a.cards.length ? 'studying' : 'finished', queue: a.cards }
    case 'reveal':
      return s.status === 'studying' ? { ...s, revealed: true } : s
    case 'rated': {
      const rest = s.queue.slice(1)
      const queue = a.rating === 1 ? [...rest, a.card] : rest
      return {
        ...s,
        queue,
        revealed: false,
        reviewed: s.reviewed + 1,
        counts: { ...s.counts, [a.rating]: s.counts[a.rating] + 1 },
        status: queue.length ? 'studying' : 'finished',
      }
    }
    case 'failed':
      return { ...s, status: 'error', error: a.message }
  }
}

/** Mastery (0-1) to a ring colour on a single-hue sequential scale, light to deep blue. */
export function masteryColor(m: number): string {
  const t = Math.max(0, Math.min(1, m))
  // Interpolate in OKLCH so steps look perceptually even.
  const l = 0.88 - 0.46 * t
  const c = 0.05 + 0.15 * t
  return `oklch(${l.toFixed(3)} ${c.toFixed(3)} 255)`
}
