import { describe, expect, it } from 'vitest'
import { createSSEParser, readSSE, type SSEMessage } from './sse'

function collect() {
  const out: SSEMessage[] = []
  return { out, parser: createSSEParser(m => out.push(m)) }
}

describe('createSSEParser', () => {
  it('parses events split across arbitrary chunk boundaries', () => {
    const { out, parser } = collect()
    const raw = 'event: step\ndata: {"a":1}\n\nevent: text\ndata: hel\ndata: lo\n\n'
    for (const ch of raw) parser.push(ch)
    expect(out).toEqual([
      { event: 'step', data: '{"a":1}' },
      { event: 'text', data: 'hel\nlo' },
    ])
  })

  it('handles CRLF, comments and the default event name', () => {
    const { out, parser } = collect()
    parser.push(': ping\r\ndata: x\r\n\r\n')
    expect(out).toEqual([{ event: 'message', data: 'x' }])
  })

  it('flushes a final event without a trailing blank line', () => {
    const { out, parser } = collect()
    parser.push('event: done\ndata: {}')
    parser.end()
    expect(out).toEqual([{ event: 'done', data: '{}' }])
  })
})

describe('readSSE', () => {
  it('reads a streamed fetch body', async () => {
    const enc = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode('event: text\ndata: "a"\n'))
        c.enqueue(enc.encode('\nevent: done\ndata: 1\n\n'))
        c.close()
      },
    })
    const out: SSEMessage[] = []
    await readSSE(new Response(body), m => out.push(m))
    expect(out.map(m => m.event)).toEqual(['text', 'done'])
  })
})
