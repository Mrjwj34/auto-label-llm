import { useEffect, useMemo, useRef, useState } from 'react'

import { API_BASE_URL } from '../api'
import type { AnnotationRecord, ImageRecord } from '../types'
import { clsx } from '../utils'

type PointMode = 0 | 1

type ImageStageProps = {
  image: ImageRecord | null
  annotations: AnnotationRecord[]
  selectedAnnotationId: number | null
  draftBox: [number, number, number, number] | null
  draftPoints: Array<{ x: number; y: number; label: 0 | 1 }>
  drawEnabled: boolean
  pointMode: PointMode | null
  onSelectAnnotation: (annotationId: number | null) => void
  onDraftBoxChange: (bbox: [number, number, number, number] | null) => void
  onPointAppend: (point: { x: number; y: number; label: 0 | 1 }) => void
}

type StageBox = { left: number; top: number; width: number; height: number }

export function ImageStage({
  image,
  annotations,
  selectedAnnotationId,
  draftBox,
  draftPoints,
  drawEnabled,
  pointMode,
  onSelectAnnotation,
  onDraftBoxChange,
  onPointAppend,
}: ImageStageProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const [stageBox, setStageBox] = useState<StageBox | null>(null)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    const update = () => {
      const wrap = wrapRef.current
      const img = imageRef.current
      if (!wrap || !img) return
      const wrapRect = wrap.getBoundingClientRect()
      const imgRect = img.getBoundingClientRect()
      setStageBox({
        left: imgRect.left - wrapRect.left,
        top: imgRect.top - wrapRect.top,
        width: imgRect.width,
        height: imgRect.height,
      })
    }
    update()
    const resizeObserver = new ResizeObserver(update)
    if (wrapRef.current) resizeObserver.observe(wrapRef.current)
    window.addEventListener('resize', update)
    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [image?.id])

  const overlayStyle = useMemo(() => {
    if (!stageBox) return { display: 'none' }
    return {
      left: `${stageBox.left}px`,
      top: `${stageBox.top}px`,
      width: `${stageBox.width}px`,
      height: `${stageBox.height}px`,
    }
  }, [stageBox])

  const toNormalized = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!stageBox) return null
    const rect = event.currentTarget.getBoundingClientRect()
    const x = (event.clientX - rect.left) / rect.width
    const y = (event.clientY - rect.top) / rect.height
    return {
      x: Math.min(1, Math.max(0, x)),
      y: Math.min(1, Math.max(0, y)),
    }
  }

  return (
    <div className="image-stage" ref={wrapRef}>
      {image ? (
        <>
          <img
            ref={imageRef}
            alt={image.filename}
            className="image-stage-image"
            onLoad={() => {
              const wrap = wrapRef.current
              const img = imageRef.current
              if (!wrap || !img) return
              const wrapRect = wrap.getBoundingClientRect()
              const imgRect = img.getBoundingClientRect()
              setStageBox({
                left: imgRect.left - wrapRect.left,
                top: imgRect.top - wrapRect.top,
                width: imgRect.width,
                height: imgRect.height,
              })
            }}
            src={`${API_BASE_URL}${image.file_url}`}
          />
          <svg
            className={clsx('image-overlay', drawEnabled && 'is-draw')}
            style={overlayStyle}
            onPointerDown={(event) => {
              const point = toNormalized(event)
              if (!point) return
              if (pointMode !== null) {
                onPointAppend({ ...point, label: pointMode })
                return
              }
              if (!drawEnabled) return
              setDragStart(point)
              onDraftBoxChange([point.x, point.y, point.x, point.y])
            }}
            onPointerMove={(event) => {
              if (!dragStart || !drawEnabled) return
              const point = toNormalized(event)
              if (!point) return
              onDraftBoxChange([
                Math.min(dragStart.x, point.x),
                Math.min(dragStart.y, point.y),
                Math.max(dragStart.x, point.x),
                Math.max(dragStart.y, point.y),
              ])
            }}
            onPointerUp={() => setDragStart(null)}
            viewBox="0 0 1000 1000"
          >
            {annotations.map((annotation) => {
              const isSelected = annotation.id === selectedAnnotationId
              return (
                <g key={annotation.id} onClick={() => onSelectAnnotation(annotation.id)}>
                  {annotation.polygon && annotation.polygon.length >= 3 ? (
                    <polygon
                      className={clsx('annotation-polygon', isSelected && 'is-selected')}
                      points={annotation.polygon.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')}
                    />
                  ) : null}
                  {annotation.bbox ? (
                    <rect
                      className={clsx('annotation-box', isSelected && 'is-selected')}
                      x={annotation.bbox[0] * 1000}
                      y={annotation.bbox[1] * 1000}
                      width={(annotation.bbox[2] - annotation.bbox[0]) * 1000}
                      height={(annotation.bbox[3] - annotation.bbox[1]) * 1000}
                    />
                  ) : null}
                </g>
              )
            })}
            {draftBox ? (
              <rect
                className="draft-box"
                x={draftBox[0] * 1000}
                y={draftBox[1] * 1000}
                width={(draftBox[2] - draftBox[0]) * 1000}
                height={(draftBox[3] - draftBox[1]) * 1000}
              />
            ) : null}
            {draftPoints.map((point, index) => (
              <circle
                key={`${point.x}-${point.y}-${index}`}
                className={clsx('draft-point', point.label === 1 ? 'is-positive' : 'is-negative')}
                cx={point.x * 1000}
                cy={point.y * 1000}
                r="10"
              />
            ))}
          </svg>
        </>
      ) : (
        <div className="stage-empty">选择图片后在此查看和编辑标注</div>
      )}
    </div>
  )
}
