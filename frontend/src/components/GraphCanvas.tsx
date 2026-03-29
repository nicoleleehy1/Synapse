import { useCallback, useEffect, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { forceCollide } from 'd3-force'
import { Plus } from 'lucide-react'
import type { FGData, FGNode, FGLink } from '../types/graph'

interface Props {
  data: FGData
  selectedNodeId: string | null
  onNodeClick: (node: FGNode) => void
  onAddNode: (parentNode: FGNode) => void
  width: number
  height: number
}

const FONT_SIZE = 11
const PAD_H     = 12
const PAD_V     = 7
const RADIUS    = 7
const MAX_CHARS = 24
const CHAR_W    = 6.2

function estimateHalfWidth(name: string): number {
  const label = name.length > MAX_CHARS ? name.slice(0, MAX_CHARS - 1) + '…' : name
  return label.length * CHAR_W / 2 + PAD_H
}

function drawRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

export function GraphCanvas({ data, selectedNodeId, onNodeClick, onAddNode, width, height }: Props) {
  const fgRef = useRef<any>(null)

  // Hover add-button state
  const [hoveredNode, setHoveredNode] = useState<FGNode | null>(null)
  const [btnPos, setBtnPos] = useState({ x: 0, y: 0 })
  const hideTimer = useRef<ReturnType<typeof setTimeout>>()
  const rafRef    = useRef<number>()

  // Edge tooltip state
  const [hoveredLink, setHoveredLink] = useState<FGLink | null>(null)
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })

  // ── Collision force ───────────────────────────────────────────────────
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    fg.d3Force('collision', forceCollide((node: FGNode) => estimateHalfWidth(node.name ?? '') + 6))
    fg.d3Force('charge')?.strength(-400)
    fg.d3Force('link')?.distance(120)
    fg.d3ReheatSimulation?.()
  }, [data.nodes.length])

  // ── Hover add-button: continuously track node position via rAF ────────
  useEffect(() => {
    cancelAnimationFrame(rafRef.current!)
    if (!hoveredNode) return

    const tick = () => {
      const fg = fgRef.current
      if (!fg || !hoveredNode) return
      const nodeH = FONT_SIZE + PAD_V * 2
      const pos = fg.graph2ScreenCoords(
        hoveredNode.x ?? 0,
        (hoveredNode.y ?? 0) + nodeH / 2 + 14,
      )
      setBtnPos(pos)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current!)
  }, [hoveredNode])

  const handleNodeHover = useCallback((node: FGNode | null) => {
    clearTimeout(hideTimer.current)
    if (node) {
      setHoveredNode(node)
    } else {
      // Small delay so cursor can move from node to button without it vanishing
      hideTimer.current = setTimeout(() => setHoveredNode(null), 180)
    }
  }, [])

  // ── Node renderer ─────────────────────────────────────────────────────
  const nodeCanvasObject = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D) => {
      const isSelected = node.id === selectedNodeId
      const label = node.name.length > MAX_CHARS ? node.name.slice(0, MAX_CHARS - 1) + '…' : node.name

      ctx.font = `500 ${FONT_SIZE}px Inter, system-ui, sans-serif`
      const textW = ctx.measureText(label).width
      const nodeW = textW + PAD_H * 2
      const nodeH = FONT_SIZE + PAD_V * 2
      const x = (node.x ?? 0) - nodeW / 2
      const y = (node.y ?? 0) - nodeH / 2

      if (isSelected) {
        drawRoundedRect(ctx, x - 2.5, y - 2.5, nodeW + 5, nodeH + 5, RADIUS + 2)
        ctx.strokeStyle = '#0a0a0a'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      drawRoundedRect(ctx, x, y, nodeW, nodeH, RADIUS)
      ctx.fillStyle = node.color ?? '#d4d4d4'
      ctx.fill()

      ctx.fillStyle = node.textColor ?? '#0a0a0a'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, node.x ?? 0, node.y ?? 0)
    },
    [selectedNodeId],
  )

  const nodePointerAreaPaint = useCallback(
    (node: FGNode, color: string, ctx: CanvasRenderingContext2D) => {
      ctx.font = `500 ${FONT_SIZE}px Inter, system-ui, sans-serif`
      const label = node.name.length > MAX_CHARS ? node.name.slice(0, MAX_CHARS - 1) + '…' : node.name
      const textW = ctx.measureText(label).width
      const nodeW = textW + PAD_H * 2
      const nodeH = FONT_SIZE + PAD_V * 2
      ctx.fillStyle = color
      ctx.fillRect((node.x ?? 0) - nodeW / 2, (node.y ?? 0) - nodeH / 2, nodeW, nodeH)
    },
    [],
  )

  // ── Link renderer ─────────────────────────────────────────────────────
  const linkCanvasObject = useCallback(
    (link: FGLink, ctx: CanvasRenderingContext2D) => {
      const src = link.source as FGNode
      const tgt = link.target as FGNode
      if (src.x == null || src.y == null || tgt.x == null || tgt.y == null) return

      const isHovered = hoveredLink?.id === link.id
      ctx.beginPath()
      ctx.moveTo(src.x, src.y)
      ctx.lineTo(tgt.x, tgt.y)
      ctx.strokeStyle = isHovered ? 'rgba(0,0,0,0.4)' : (link.color ?? 'rgba(0,0,0,0.08)')
      ctx.lineWidth = isHovered ? 1.5 : 0.75
      ctx.stroke()
    },
    [hoveredLink],
  )

  return (
    <div
      style={{ width, height, position: 'relative' }}
      onMouseMove={(e) => setMousePos({ x: e.clientX, y: e.clientY })}
    >
      <ForceGraph2D
        ref={fgRef}
        graphData={data as never}
        nodeId="id"
        linkSource="source"
        linkTarget="target"
        width={width}
        height={height}
        backgroundColor="#ffffff"
        nodeCanvasObject={nodeCanvasObject as never}
        nodeCanvasObjectMode={() => 'replace'}
        nodePointerAreaPaint={nodePointerAreaPaint as never}
        linkCanvasObject={linkCanvasObject as never}
        linkCanvasObjectMode={() => 'replace'}
        onNodeClick={(node) => onNodeClick(node as unknown as FGNode)}
        onNodeHover={(node) => handleNodeHover((node as FGNode) ?? null)}
        onLinkHover={(link) => setHoveredLink((link as FGLink) ?? null)}
        linkHoverPrecision={6}
        nodeLabel=""
        linkLabel=""
        cooldownTicks={150}
        d3AlphaDecay={0.015}
        d3VelocityDecay={0.25}
      />

      {/* Hover add-node button — appears below the hovered node */}
      {hoveredNode && (
        <button
          style={{ position: 'absolute', left: btnPos.x - 12, top: btnPos.y - 12 }}
          className="w-6 h-6 flex items-center justify-center bg-foreground text-background rounded-sm hover:bg-chart-4 transition-colors z-20"
          onMouseEnter={() => clearTimeout(hideTimer.current)}
          onMouseLeave={() => { hideTimer.current = setTimeout(() => setHoveredNode(null), 180) }}
          onClick={(e) => { e.stopPropagation(); onAddNode(hoveredNode) }}
          title={`Add node connected to ${hoveredNode.name}`}
        >
          <Plus size={13} />
        </button>
      )}

      {/* Edge tooltip */}
      {hoveredLink && (
        <div
          className="fixed z-50 pointer-events-none"
          style={{ left: mousePos.x + 14, top: mousePos.y - 38 }}
        >
          <div className="bg-foreground text-background text-xs font-medium px-2.5 py-1.5 rounded whitespace-nowrap">
            <span className="font-mono">{hoveredLink.type}</span>
            {hoveredLink.description && (
              <span className="text-chart-1 font-normal ml-1.5 max-w-[200px] truncate inline-block align-bottom">
                — {hoveredLink.description}
              </span>
            )}
            <span className="text-chart-2 ml-2">{(hoveredLink.confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
    </div>
  )
}
