import { useCallback, useRef } from 'react'
import { Loader2 } from 'lucide-react'
import type { DocumentStatus } from '../types/graph'
import { progressPercent, stageLabel } from '../lib/progress'

interface Props {
  onUpload: (file: File) => void
  uploading: boolean
  status: DocumentStatus | null
  error: string | null
}

export function FileUpload({ onUpload, uploading, status, error }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const file = e.dataTransfer.files[0]
      if (file?.type === 'application/pdf') onUpload(file)
    },
    [onUpload],
  )

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) onUpload(file)
      e.target.value = ''
    },
    [onUpload],
  )

  const isProcessing = uploading || status?.status === 'processing' || status?.status === 'queued'

  return (
    <div className="space-y-3">
      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => !isProcessing && inputRef.current?.click()}
        className={`
          border border-dashed border-border rounded px-5 py-7 text-center transition-colors
          ${isProcessing
            ? 'cursor-not-allowed opacity-40'
            : 'cursor-pointer hover:border-chart-3 hover:bg-secondary'
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={handleChange}
          disabled={isProcessing}
        />
        <p className="text-sm text-chart-3">
          Drop PDF here or{' '}
          <span className="text-foreground underline underline-offset-2">browse</span>
        </p>
        <p className="text-2xs text-chart-2 mt-1">PDF files only</p>
      </div>

      {/* Error */}
      {error && (
        <p className="text-xs text-foreground border border-border rounded-sm px-3 py-2 bg-secondary">
          {error}
        </p>
      )}

      {/* Status */}
      {status && (
        <div className="space-y-3 pt-1">
          <div className="flex items-center justify-between gap-2">
            <span
              className="text-sm font-medium text-foreground truncate"
              title={status.filename}
            >
              {status.filename}
            </span>
            <StatusPill status={status.status} />
          </div>

          {(status.status === 'processing' || status.status === 'queued') && (
            <div className="space-y-1.5" role="status" aria-live="polite">
              <div className="flex items-center gap-2 text-xs text-chart-2">
                <Loader2 size={11} className="animate-spin shrink-0" />
                <span className="truncate">{stageLabel(status)}</span>
                <span className="ml-auto tabular-nums">{progressPercent(status.progress)}%</span>
              </div>
              <div
                className="h-1 w-full rounded-sm bg-secondary overflow-hidden"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progressPercent(status.progress)}
              >
                <div
                  className="h-full bg-foreground transition-[width] duration-300 ease-out"
                  style={{ width: `${progressPercent(status.progress)}%` }}
                />
              </div>
            </div>
          )}

          {status.status === 'complete' && (
            <div className="grid grid-cols-2 gap-px bg-border border border-border rounded-sm overflow-hidden">
              <Stat label="Pages"         value={status.page_count} />
              <Stat label="Chunks"        value={status.chunk_count} />
              <Stat label="Entities"      value={status.entity_count} />
              <Stat label="Relationships" value={status.relationship_count} />
            </div>
          )}

          {status.status === 'error' && (
            <p className="text-xs text-foreground">{status.error}</p>
          )}
        </div>
      )}
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued:     'Queued',
    processing: 'Processing',
    complete:   'Complete',
    error:      'Error',
    uploading:  'Uploading',
  }
  return (
    <span className="text-2xs font-medium border border-border rounded-sm px-2 py-0.5 text-chart-3 bg-secondary shrink-0">
      {map[status] ?? status}
    </span>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-background px-3 py-2">
      <div className="text-2xs text-chart-2 uppercase tracking-wide">{label}</div>
      <div className="text-base font-semibold text-foreground mt-0.5">{value.toLocaleString()}</div>
    </div>
  )
}
