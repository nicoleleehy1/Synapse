import { describe, expect, it } from 'vitest'
import { isTerminal, progressPercent, stageLabel } from './progress'

describe('stageLabel', () => {
  it('shows per-chunk progress while extracting', () => {
    expect(stageLabel({ stage: 'extracting', chunks_processed: 3, chunk_count: 12 }))
      .toBe('Extracting entities and relationships (3/12)')
  })
  it('uses plain labels for other stages', () => {
    expect(stageLabel({ stage: 'embedding', chunks_processed: 0, chunk_count: 12 })).toBe('Embedding passages')
  })
})

describe('progressPercent', () => {
  it('clamps and rounds', () => {
    expect(progressPercent(0.456)).toBe(46)
    expect(progressPercent(-1)).toBe(0)
    expect(progressPercent(3)).toBe(100)
    expect(progressPercent(Number.NaN)).toBe(0)
  })
})

describe('isTerminal', () => {
  it('detects finished jobs', () => {
    expect(isTerminal({ status: 'complete' })).toBe(true)
    expect(isTerminal({ status: 'error' })).toBe(true)
    expect(isTerminal({ status: 'processing' })).toBe(false)
    expect(isTerminal(null)).toBe(false)
  })
})
