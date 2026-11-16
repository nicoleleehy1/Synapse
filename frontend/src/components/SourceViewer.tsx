import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react'
import { documentPdfUrl, getChunk } from '../api/client'
import type { ChunkDetail } from '../types/graph'

interface Props {
  chunkId: string
  onClose: () => void
}

type PdfDoc = import('pdfjs-dist').PDFDocumentProxy

// pdf.js is large: load it (and its worker) only when a source is first opened.
let pdfjsPromise: Promise<typeof import('pdfjs-dist')> | null = null
function loadPdfjs() {
  pdfjsPromise ??= Promise.all([
    import('pdfjs-dist'),
    import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
  ]).then(([pdfjs, worker]) => {
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default
    return pdfjs
  })
  return pdfjsPromise
}

/** The source page of a passage, rendered from the original PDF with the passage highlighted. */
export function SourceViewer({ chunkId, onClose }: Props) {
  const [chunk, setChunk] = useState<ChunkDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pdf, setPdf] = useState<PdfDoc | null>(null)
  const [page, setPage] = useState(1)
  const [rendering, setRendering] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const markRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Capture phase, so Escape closes only this viewer and not a study session underneath.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopImmediatePropagation(); onClose() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  useEffect(() => {
    let cancelled = false
    let doc: PdfDoc | null = null
    getChunk(chunkId)
      .then(async (c) => {
        if (cancelled) return
        setChunk(c)
        setPage(c.highlights[0]?.page ?? c.page_number)
        if (!c.has_pdf) return
        const pdfjs = await loadPdfjs()
        doc = await pdfjs.getDocument({ url: documentPdfUrl(c.document_id) }).promise
        if (cancelled) void doc.destroy()
        else setPdf(doc)
      })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load the source.') })
    return () => { cancelled = true; void doc?.destroy() }
  }, [chunkId])

  useEffect(() => {
    if (!pdf || !canvasRef.current) return
    let task: { cancel: () => void; promise: Promise<void> } | null = null
    let cancelled = false
    setRendering(true)
    pdf.getPage(page).then((p) => {
      if (cancelled || !canvasRef.current) return
      const canvas = canvasRef.current
      const cssWidth = Math.min(720, window.innerWidth - 64)
      const base = p.getViewport({ scale: 1 })
      const ratio = window.devicePixelRatio || 1
      const viewport = p.getViewport({ scale: (cssWidth / base.width) * ratio })
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = `${cssWidth}px`
      canvas.style.height = `${viewport.height / ratio}px`
      task = p.render({ canvas, canvasContext: canvas.getContext('2d')!, viewport })
      return task.promise
    })
      .then(() => { if (!cancelled) markRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) })
      .catch(() => {})
      .finally(() => { if (!cancelled) setRendering(false) })
    return () => { cancelled = true; task?.cancel() }
  }, [pdf, page])

  const pages = chunk ? [...new Set(chunk.highlights.map(h => h.page))].sort((a, b) => a - b) : []
  const rects = chunk?.highlights.filter(h => h.page === page) ?? []
  const total = pdf?.numPages ?? 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 backdrop-blur-xs px-4 py-6"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-[768px] max-h-full flex flex-col bg-background border border-border rounded-sm">
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-border">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground truncate">{chunk?.document_name ?? 'Source'}</p>
            <p className="text-2xs text-chart-2">
              {chunk ? `Page ${page}${total ? ` of ${total}` : ''}` : 'Loading…'}
              {pages.length > 1 && ` · passage spans pages ${pages[0]}-${pages[pages.length - 1]}`}
            </p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {pdf && (
              <>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-1.5 text-chart-2 hover:text-foreground disabled:opacity-30"
                  aria-label="Previous page"
                >
                  <ChevronLeft size={16} />
                </button>
                <button
                  onClick={() => setPage(p => Math.min(total, p + 1))}
                  disabled={page >= total}
                  className="p-1.5 text-chart-2 hover:text-foreground disabled:opacity-30"
                  aria-label="Next page"
                >
                  <ChevronRight size={16} />
                </button>
                <a
                  href={documentPdfUrl(chunk!.document_id)}
                  target="_blank"
                  rel="noreferrer"
                  className="p-1.5 text-chart-2 hover:text-foreground"
                  aria-label="Open PDF in a new tab"
                >
                  <ExternalLink size={15} />
                </a>
              </>
            )}
            <button onClick={onClose} className="p-1.5 text-chart-2 hover:text-foreground" aria-label="Close">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto bg-secondary/40 p-4">
          {error && <p className="text-xs text-chart-4">{error}</p>}
          {chunk && !chunk.has_pdf && (
            <div className="space-y-2">
              <p className="text-2xs text-chart-2">The original PDF wasn't kept for this document, so here is the passage text.</p>
              <blockquote className="border-l-2 border-foreground pl-3 text-sm text-foreground leading-relaxed">{chunk.text}</blockquote>
            </div>
          )}
          {chunk?.has_pdf && (
            <div className="relative mx-auto w-fit shadow-sm bg-white">
              <canvas ref={canvasRef} className="block" />
              {!rendering && rects.map((r, i) => (
                <div
                  key={i}
                  ref={i === 0 ? markRef : undefined}
                  className="absolute pointer-events-none rounded-[2px] bg-yellow-300/45 mix-blend-multiply ring-1 ring-yellow-500/40"
                  style={{
                    left: `${r.x0 * 100}%`,
                    top: `${r.y0 * 100}%`,
                    width: `${(r.x1 - r.x0) * 100}%`,
                    height: `${(r.y1 - r.y0) * 100}%`,
                  }}
                />
              ))}
              {rendering && <div className="absolute inset-0 flex items-center justify-center text-xs text-chart-2">Rendering…</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
