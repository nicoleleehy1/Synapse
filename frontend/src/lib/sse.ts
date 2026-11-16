/**
 * Minimal Server-Sent Events parser for fetch() response bodies.
 *
 * EventSource only supports GET, but asking a question is a POST, so the
 * stream is read from fetch and parsed here (spec: event/data fields,
 * blank-line delimited, `data` lines joined with "\n", comments ignored).
 */
export interface SSEMessage {
  event: string
  data: string
}

export function createSSEParser(onMessage: (msg: SSEMessage) => void) {
  let buffer = ''
  let event = 'message'
  let data: string[] = []

  const dispatch = () => {
    if (data.length) onMessage({ event, data: data.join('\n') })
    event = 'message'
    data = []
  }

  return {
    push(chunk: string) {
      buffer += chunk
      const lines = buffer.split(/\r\n|\r|\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line === '') dispatch()
        else if (line.startsWith(':')) continue
        else {
          const idx = line.indexOf(':')
          const field = idx === -1 ? line : line.slice(0, idx)
          const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '')
          if (field === 'event') event = value
          else if (field === 'data') data.push(value)
        }
      }
    },
    end() {
      if (buffer) this.push('\n')
      dispatch()
    },
  }
}

export async function readSSE(
  response: Response,
  onMessage: (msg: SSEMessage) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error('Streaming is not supported by this browser.')
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  const parser = createSSEParser(onMessage)
  try {
    while (!signal?.aborted) {
      const { value, done } = await reader.read()
      if (done) break
      parser.push(value)
    }
    parser.end()
  } finally {
    reader.releaseLock()
  }
}
