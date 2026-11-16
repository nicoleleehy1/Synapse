import { useEffect, useState } from 'react'
import { Flame, Sparkles } from 'lucide-react'
import { generateCards, getStudyStats } from '../api/client'
import { masteryColor } from '../lib/study'
import type { StudyStats } from '../types/graph'

interface Props {
  /** Bumped by the parent after documents change or reviews happen, to refetch. */
  refreshKey: number
  canGenerate: boolean
  showMastery: boolean
  onToggleMastery: (on: boolean) => void
  onStudy: () => void
  onGenerated: () => void
}

/** Sidebar summary of the spaced-repetition deck: what's due, streak, recent activity. */
export function StudyPanel({ refreshKey, canGenerate, showMastery, onToggleMastery, onStudy, onGenerated }: Props) {
  const [stats, setStats] = useState<StudyStats | null>(null)
  const [generating, setGenerating] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getStudyStats().then(s => { if (!cancelled) setStats(s) }).catch(() => {})
    return () => { cancelled = true }
  }, [refreshKey])

  const generate = async () => {
    setGenerating(true)
    setNote(null)
    try {
      const n = await generateCards(12)
      setNote(n ? `Added ${n} card${n === 1 ? '' : 's'}.` : 'Every relationship already has a card.')
      onGenerated()
    } catch (e: unknown) {
      setNote(e instanceof Error ? e.message : 'Could not generate cards.')
    } finally {
      setGenerating(false)
    }
  }

  const ready = stats ? stats.due + Math.min(stats.new, 20) : 0
  const peak = Math.max(1, ...(stats?.activity ?? [0]))

  return (
    <div className="space-y-3">
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-3 gap-2 text-center">
          <Stat value={stats.due} label="due" />
          <Stat value={stats.new} label="new" />
          <Stat
            value={stats.retention_30d === null ? '–' : `${Math.round(stats.retention_30d * 100)}%`}
            label="recall"
          />
        </div>
      )}

      {stats && stats.total > 0 && (
        <div className="flex items-end justify-between gap-3">
          <div className="flex items-end gap-[3px] h-6" aria-label="Reviews per day, last 14 days">
            {stats.activity.map((n, i) => (
              <div
                key={i}
                title={`${n} review${n === 1 ? '' : 's'}`}
                className={`w-[5px] rounded-[1px] ${n ? 'bg-foreground' : 'bg-border'}`}
                style={{ height: `${n ? Math.max(15, (n / peak) * 100) : 12}%` }}
              />
            ))}
          </div>
          <p className="text-2xs text-chart-2 flex items-center gap-1">
            <Flame size={12} className={stats.streak_days ? 'text-foreground' : ''} />
            {stats.streak_days} day streak
          </p>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={onStudy}
          disabled={!ready}
          className="flex-1 text-xs font-medium bg-foreground text-background rounded-sm px-3 py-2 hover:opacity-90 transition-opacity disabled:opacity-30"
        >
          {ready ? `Study ${ready} card${ready === 1 ? '' : 's'}` : 'Nothing due'}
        </button>
        <button
          onClick={generate}
          disabled={!canGenerate || generating}
          title="Write flashcards from relationships in the graph"
          className="flex items-center gap-1.5 text-xs text-chart-3 border border-border rounded-sm px-3 py-2 hover:border-chart-3 hover:text-foreground transition-colors disabled:opacity-40"
        >
          <Sparkles size={13} />
          {generating ? 'Writing…' : 'Make cards'}
        </button>
      </div>
      {note && <p className="text-2xs text-chart-2">{note}</p>}

      {stats && stats.total > 0 && (
        <label className="flex items-center justify-between gap-2 text-xs text-chart-4 cursor-pointer select-none">
          <span className="flex items-center gap-2">
            <input type="checkbox" checked={showMastery} onChange={e => onToggleMastery(e.target.checked)} className="accent-foreground" />
            Mastery heatmap
          </span>
          {showMastery && (
            <span className="flex items-center gap-1 text-2xs text-chart-2">
              0%
              <span
                className="inline-block w-14 h-1.5 rounded-full"
                style={{ background: `linear-gradient(to right, ${masteryColor(0)}, ${masteryColor(0.5)}, ${masteryColor(1)})` }}
              />
              100%
            </span>
          )}
        </label>
      )}
    </div>
  )
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="border border-border rounded-sm py-1.5">
      <p className="text-sm font-semibold text-foreground tabular-nums">{value}</p>
      <p className="text-2xs text-chart-2">{label}</p>
    </div>
  )
}
