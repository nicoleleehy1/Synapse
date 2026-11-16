import { describe, expect, it } from 'vitest'
import { agentReducer, initialAgentState, type AgentState } from './useAgentQuery'
import type { AgentEvent } from '../types/graph'

const run = (events: AgentEvent[]): AgentState =>
  events.reduce(
    (s, event) => agentReducer(s, { type: 'event', event }),
    agentReducer(initialAgentState, { type: 'start' }),
  )

describe('agentReducer', () => {
  it('tracks steps, their results, and the streamed answer', () => {
    const s = run([
      { type: 'step', id: 't1', tool: 'search_passages', input: { query: 'x' } },
      { type: 'text', delta: 'Thinking out loud' },
      { type: 'text_reset' },
      { type: 'step_result', id: 't1', summary: '3 passages', is_error: false },
      { type: 'text', delta: 'Answer ' },
      { type: 'text', delta: '[1]' },
    ])
    expect(s.status).toBe('running')
    expect(s.steps).toEqual([
      { id: 't1', tool: 'search_passages', input: { query: 'x' }, summary: '3 passages', is_error: false },
    ])
    expect(s.answer).toBe('Answer [1]')
  })

  it('finishes with the final result', () => {
    const s = run([
      { type: 'text', delta: 'partial' },
      {
        type: 'done', answer: 'final', sources: [], graph: { nodes: [], edges: [] },
        highlight_ids: ['e1'], steps: 1, latency_ms: 10,
      },
    ])
    expect(s.status).toBe('done')
    expect(s.answer).toBe('final')
    expect(s.result?.highlight_ids).toEqual(['e1'])
  })

  it('records errors and resets on a new question', () => {
    const failed = run([{ type: 'error', message: 'boom' }])
    expect(failed).toMatchObject({ status: 'error', error: 'boom' })
    expect(agentReducer(failed, { type: 'start' })).toEqual({ ...initialAgentState, status: 'running' })
  })
})
