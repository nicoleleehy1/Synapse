import { useCallback, useReducer, useRef } from 'react'
import { streamQuery } from '../api/client'
import type { AgentDone, AgentEvent, AgentStep } from '../types/graph'

export interface AgentState {
  status: 'idle' | 'running' | 'done' | 'error'
  steps: AgentStep[]
  answer: string
  result: AgentDone | null
  error: string | null
}

export const initialAgentState: AgentState = {
  status: 'idle', steps: [], answer: '', result: null, error: null,
}

type Action = { type: 'start' } | { type: 'event'; event: AgentEvent } | { type: 'fail'; message: string }

export function agentReducer(state: AgentState, action: Action): AgentState {
  switch (action.type) {
    case 'start':
      return { ...initialAgentState, status: 'running' }
    case 'fail':
      return { ...state, status: 'error', error: action.message }
    case 'event': {
      const e = action.event
      switch (e.type) {
        case 'step':
          return { ...state, steps: [...state.steps, { id: e.id, tool: e.tool, input: e.input }] }
        case 'step_result':
          return {
            ...state,
            steps: state.steps.map(s => (s.id === e.id ? { ...s, summary: e.summary, is_error: e.is_error } : s)),
          }
        case 'text':
          return { ...state, answer: state.answer + e.delta }
        case 'text_reset':
          return { ...state, answer: '' }
        case 'done':
          return { ...state, status: 'done', answer: e.answer || state.answer, result: e }
        case 'error':
          return { ...state, status: 'error', error: e.message }
        default:
          return state
      }
    }
  }
}

/** Run the GraphRAG agent and expose its live reasoning trace and streamed answer. */
export function useAgentQuery(onDone?: (result: AgentDone) => void) {
  const [state, dispatch] = useReducer(agentReducer, initialAgentState)
  const abortRef = useRef<AbortController | null>(null)

  const ask = useCallback(async (query: string, documentId?: string) => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    dispatch({ type: 'start' })
    try {
      await streamQuery(query, (event) => {
        dispatch({ type: 'event', event })
        if (event.type === 'done') onDone?.(event)
      }, { documentId, signal: ctrl.signal })
    } catch (e: unknown) {
      if (ctrl.signal.aborted) return
      dispatch({ type: 'fail', message: e instanceof Error ? e.message : 'Query failed' })
    }
  }, [onDone])

  const cancel = useCallback(() => abortRef.current?.abort(), [])

  return { state, ask, cancel }
}
