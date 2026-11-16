import { describe, expect, it } from 'vitest'
import { splitCitations } from './citations'

describe('splitCitations', () => {
  it('splits single and grouped markers', () => {
    expect(splitCitations('Alpha [1] and beta [2, 3].')).toEqual([
      { kind: 'text', text: 'Alpha ' },
      { kind: 'cite', n: 1 },
      { kind: 'text', text: ' and beta ' },
      { kind: 'cite', n: 2 },
      { kind: 'cite', n: 3 },
      { kind: 'text', text: '.' },
    ])
  })

  it('leaves non-numeric brackets alone', () => {
    expect(splitCitations('see [note]')).toEqual([{ kind: 'text', text: 'see [note]' }])
  })
})
