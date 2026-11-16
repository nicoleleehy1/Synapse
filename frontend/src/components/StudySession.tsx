import { useCallback, useEffect, useReducer, useState } from 'react'
import { FileText, X } from 'lucide-react'
import { getDueCards, reviewCard } from '../api/client'
import { RATINGS, formatInterval, initialSession, sessionReducer } from '../lib/study'
import type { Rating } from '../types/graph'

interface Props {
  onClose: () => void
  onOpenSource: (chunkId: string) => void
  /** Called after each review so the mastery heatmap can update live. */
  onReviewed: () => void
}

const RATING_STYLE: Record<Rating, string> = {
  1: 'hover:border-red-400 hover:text-red-700',
  2: 'hover:border-amber-400 hover:text-amber-700',
  3: 'hover:border-foreground hover:text-foreground',
  4: 'hover:border-sky-400 hover:text-sky-700',
}

/** A spaced-repetition review session: question, reveal, rate, next. Keys: Space reveals, 1-4 rate. */
export function StudySession({ onClose, onOpenSource, onReviewed }: Props) {
  const [s, dispatch] = useReducer(sessionReducer, initialSession)
  const [busy, setBusy] = useState(false)
  const card = s.queue[0]

  useEffect(() => {
    getDueCards(100)
      .then(cards => dispatch({ type: 'loaded', cards }))
      .catch((e: unknown) => dispatch({ type: 'failed', message: e instanceof Error ? e.message : 'Could not load cards.' }))
  }, [])

  const rate = useCallback(async (rating: Rating) => {
    if (!card || !s.revealed || busy) return
    setBusy(true)
    try {
      const updated = await reviewCard(card.id, rating)
      dispatch({ type: 'rated', rating, card: updated })
      onReviewed()
    } catch (e: unknown) {
      dispatch({ type: 'failed', message: e instanceof Error ? e.message : 'Could not save the review.' })
    } finally {
      setBusy(false)
    }
  }, [card, s.revealed, busy, onReviewed])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if ((e.key === ' ' || e.key === 'Enter') && !s.revealed) { e.preventDefault(); dispatch({ type: 'reveal' }) }
      else if (s.revealed && ['1', '2', '3', '4'].includes(e.key)) void rate(Number(e.key) as Rating)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [s.revealed, rate, onClose])

  const total = s.reviewed + s.queue.length

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 backdrop-blur-xs px-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-lg bg-background border border-border rounded-sm">
        <div className="flex items-center justify-between px-6 pt-5">
          <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest">
            {s.status === 'studying' ? `Card ${s.reviewed + 1} of ${total}` : 'Study'}
          </p>
          <button onClick={onClose} className="text-chart-2 hover:text-foreground" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        {s.status === 'studying' && (
          <div className="mx-6 mt-3 h-0.5 bg-secondary">
            <div className="h-full bg-foreground transition-all" style={{ width: `${(s.reviewed / total) * 100}%` }} />
          </div>
        )}

        <div className="px-6 py-6 min-h-[260px] flex flex-col">
          {s.status === 'loading' && <p className="text-sm text-chart-2">Loading cards…</p>}
          {s.status === 'error' && <p className="text-sm text-chart-4">{s.error}</p>}

          {s.status === 'finished' && (
            <div className="my-auto text-center space-y-2">
              <p className="text-lg font-semibold text-foreground">
                {s.reviewed ? 'Done for now' : 'Nothing due'}
              </p>
              <p className="text-sm text-chart-2">
                {s.reviewed
                  ? `${s.reviewed} review${s.reviewed === 1 ? '' : 's'}: ${RATINGS.map(r => `${s.counts[r.value]} ${r.label.toLowerCase()}`).join(', ')}.`
                  : 'Generate cards from your graph, or come back when reviews are due.'}
              </p>
              <button onClick={onClose} className="mt-3 text-xs border border-border rounded-sm px-4 py-2 hover:border-foreground">
                Close
              </button>
            </div>
          )}

          {s.status === 'studying' && card && (
            <>
              {card.entity_names.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-3">
                  {card.entity_names.map(n => (
                    <span key={n} className="text-2xs px-1.5 py-0.5 bg-secondary text-chart-4 rounded-sm">{n}</span>
                  ))}
                </div>
              )}
              <p className="text-base font-medium text-foreground leading-snug">{card.front}</p>

              {s.revealed ? (
                <div className="mt-5 pt-5 border-t border-border space-y-3">
                  <p className="text-sm text-foreground leading-relaxed">{card.back}</p>
                  {card.chunk_id && (
                    <button
                      onClick={() => onOpenSource(card.chunk_id!)}
                      className="inline-flex items-center gap-1 text-2xs text-chart-2 hover:text-foreground"
                    >
                      <FileText size={12} /> Show in source
                    </button>
                  )}
                </div>
              ) : (
                <button
                  onClick={() => dispatch({ type: 'reveal' })}
                  className="mt-auto self-center text-xs border border-border rounded-sm px-5 py-2 hover:border-foreground"
                >
                  Show answer <span className="text-chart-2 ml-1">Space</span>
                </button>
              )}
            </>
          )}
        </div>

        {s.status === 'studying' && card && s.revealed && (
          <div className="grid grid-cols-4 gap-2 px-6 pb-6">
            {RATINGS.map(r => (
              <button
                key={r.value}
                onClick={() => void rate(r.value)}
                disabled={busy}
                className={`flex flex-col items-center gap-0.5 border border-border rounded-sm py-2 text-xs text-chart-4 transition-colors disabled:opacity-40 ${RATING_STYLE[r.value]}`}
              >
                <span className="font-medium">{r.label}</span>
                <span className="text-2xs text-chart-2">{formatInterval(card.intervals[r.value])} · {r.key}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
