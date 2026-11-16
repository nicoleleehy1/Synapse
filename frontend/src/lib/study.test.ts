import { describe, expect, it } from 'vitest'
import { formatInterval, initialSession, masteryColor, sessionReducer } from './study'
import type { Card } from '../types/graph'

const card = (id: string): Card => ({
  id, front: 'Q', back: 'A', chunk_id: null, document_id: null, entity_ids: [], entity_names: [],
  state: 'new', reps: 0, lapses: 0, due_ms: 0, intervals: { 1: 600, 2: 86400, 3: 259200, 4: 1382400 },
})

describe('formatInterval', () => {
  it('picks a compact unit', () => {
    expect(formatInterval(600)).toBe('10m')
    expect(formatInterval(5 * 3600)).toBe('5h')
    expect(formatInterval(3 * 86400)).toBe('3d')
    expect(formatInterval(75 * 86400)).toBe('2.5mo')
    expect(formatInterval(400 * 86400)).toBe('1.1y')
    expect(formatInterval(10)).toBe('1m')
  })
})

describe('sessionReducer', () => {
  it('requeues cards rated Again and finishes when the queue is empty', () => {
    let s = sessionReducer(initialSession, { type: 'loaded', cards: [card('a'), card('b')] })
    expect(s.status).toBe('studying')
    s = sessionReducer(s, { type: 'reveal' })
    expect(s.revealed).toBe(true)
    s = sessionReducer(s, { type: 'rated', rating: 1, card: card('a') })
    expect(s.queue.map(c => c.id)).toEqual(['b', 'a'])
    expect(s.revealed).toBe(false)
    s = sessionReducer(s, { type: 'rated', rating: 3, card: card('b') })
    s = sessionReducer(s, { type: 'rated', rating: 4, card: card('a') })
    expect(s).toMatchObject({ status: 'finished', reviewed: 3, counts: { 1: 1, 2: 0, 3: 1, 4: 1 } })
  })

  it('finishes immediately with nothing due', () => {
    expect(sessionReducer(initialSession, { type: 'loaded', cards: [] }).status).toBe('finished')
  })
})

describe('masteryColor', () => {
  it('gets darker as mastery grows and clamps', () => {
    const l = (s: string) => Number(s.match(/oklch\(([\d.]+)/)![1])
    expect(l(masteryColor(0))).toBeGreaterThan(l(masteryColor(0.5)))
    expect(l(masteryColor(0.5))).toBeGreaterThan(l(masteryColor(1)))
    expect(masteryColor(2)).toBe(masteryColor(1))
  })
})
