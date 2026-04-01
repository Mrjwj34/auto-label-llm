<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API_BASE_URL, api } from '../api/http'

type ImageRow = {
  id: number
  project_id: number
  filename: string
  width: number | null
  height: number | null
  split: string
  status: string
  quality_score: number | null
  file_url: string
}

type AnnotationRow = {
  id: number
  image_id: number
  label: string
  bbox: [number, number, number, number] | null
  polygon: [number, number][] | null
  mask_path: string | null
  confidence: number | null
  source: string
  is_confirmed: boolean
}

type InteractionMode = 'bbox' | 'points'

type CorrectionPoint = {
  x: number
  y: number
  label: 0 | 1
}

const route = useRoute()
const router = useRouter()

const projectId = computed(() => Number(route.params.projectId))
const imageId = computed(() => Number(route.params.imageId))

const loading = ref(false)
const error = ref<string>('')

const image = ref<ImageRow | null>(null)
const annotations = ref<AnnotationRow[]>([])

const projectLabels = ref<string[]>([])
const selectedLabel = ref<string>('')
const interactionMode = ref<InteractionMode>('bbox')
const activeAnnotationId = ref<number | null>(null)
const correctionPoints = ref<CorrectionPoint[]>([])

type DrawMode = 'idle' | 'dragging' | 'armed'

const drawing = reactive({
  mode: 'idle' as DrawMode,
  startX: 0,
  startY: 0,
  curX: 0,
  curY: 0,
  pointerId: null as number | null,
  moved: false,
})

const stageRef = ref<HTMLDivElement | null>(null)
const stageSize = reactive({ width: 0, height: 0 })

function updateStageSize() {
  const stage = stageRef.value
  if (!stage) return
  const rect = stage.getBoundingClientRect()
  stageSize.width = rect.width
  stageSize.height = rect.height
}

let resizeObserver: ResizeObserver | null = null

const activeAnnotation = computed(
  () => annotations.value.find((annotation) => annotation.id === activeAnnotationId.value) ?? null
)
const canDraw = computed(
  () => interactionMode.value === 'bbox' && !!image.value && !!stageRef.value && !!selectedLabel.value
)
const canPointCorrect = computed(
  () => interactionMode.value === 'points' && !!image.value && !!stageRef.value && !!activeAnnotation.value
)

function back() {
  router.push({ name: 'project-images', params: { projectId: projectId.value } })
}

function fileSrc(): string {
  if (!image.value) return ''
  const base = API_BASE_URL.replace(/\/$/, '')
  const path = image.value.file_url.startsWith('/') ? image.value.file_url : `/${image.value.file_url}`
  return `${base}${path}`
}

function viewBox(): string {
  const w = image.value?.width ?? 1
  const h = image.value?.height ?? 1
  return `0 0 ${w} ${h}`
}

function rectPx(bbox: [number, number, number, number]) {
  const w = image.value?.width ?? 1
  const h = image.value?.height ?? 1
  const [xmin, ymin, xmax, ymax] = bbox
  return {
    x: xmin * w,
    y: ymin * h,
    width: (xmax - xmin) * w,
    height: (ymax - ymin) * h,
  }
}

function polygonPoints(polygon: [number, number][]) {
  const w = image.value?.width ?? 1
  const h = image.value?.height ?? 1
  return polygon.map(([x, y]) => `${x * w},${y * h}`).join(' ')
}

function pointPx(point: CorrectionPoint) {
  const w = image.value?.width ?? 1
  const h = image.value?.height ?? 1
  return {
    cx: point.x * w,
    cy: point.y * h,
  }
}

function clamp01(n: number): number {
  return Math.max(0, Math.min(1, n))
}

function pointToNorm(ev: PointerEvent): { x: number; y: number } {
  const stage = stageRef.value
  if (!stage) return { x: 0, y: 0 }
  const rect = stage.getBoundingClientRect()
  const x = clamp01((ev.clientX - rect.left) / rect.width)
  const y = clamp01((ev.clientY - rect.top) / rect.height)
  return { x, y }
}

function userUnitsFromScreenPx(px: number): number {
  const imgW = image.value?.width ?? 0
  if (!imgW) return px

  const stageW = stageSize.width || stageRef.value?.getBoundingClientRect().width || 0
  if (!stageW) return px

  const scale = stageW / imgW
  if (scale <= 0) return px

  return px / scale
}

const labelFontSize = computed(() => {
  // Keep label readable on screen regardless of original image resolution.
  const desiredPx = 12
  const userUnits = userUnitsFromScreenPx(desiredPx)
  return Math.max(6, Math.min(48, userUnits))
})

const labelOffsetX = computed(() => userUnitsFromScreenPx(6))
const labelOffsetY = computed(() => userUnitsFromScreenPx(16))
const pointRadius = computed(() => Math.max(4, Math.min(18, userUnitsFromScreenPx(6))))

const draftBbox = computed<[number, number, number, number] | null>(() => {
  if (drawing.mode === 'idle') return null
  const xmin = Math.min(drawing.startX, drawing.curX)
  const ymin = Math.min(drawing.startY, drawing.curY)
  const xmax = Math.max(drawing.startX, drawing.curX)
  const ymax = Math.max(drawing.startY, drawing.curY)
  return [xmin, ymin, xmax, ymax]
})

async function fetchImageAndAnnotations() {
  if (!Number.isFinite(imageId.value) || imageId.value <= 0) return
  loading.value = true
  error.value = ''
  try {
    const imgResp = await api.get(`/api/images/${imageId.value}`)
    image.value = imgResp.data?.data ?? null

    const annResp = await api.get(`/api/images/${imageId.value}/annotations`)
    const rows = annResp.data?.data ?? []
    annotations.value = rows
    if (activeAnnotationId.value != null && !rows.some((annotation: AnnotationRow) => annotation.id === activeAnnotationId.value)) {
      activeAnnotationId.value = null
      correctionPoints.value = []
      interactionMode.value = 'bbox'
    }
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    loading.value = false
  }
}

async function fetchProjectSettings() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/settings`)
    const labels = resp.data?.data?.labels
    if (Array.isArray(labels)) {
      projectLabels.value = labels.filter((x: any) => typeof x === 'string' && x.trim()).map((s: string) => s.trim())
      if (!selectedLabel.value && projectLabels.value.length > 0) selectedLabel.value = projectLabels.value[0] ?? ''
      if (selectedLabel.value && !projectLabels.value.includes(selectedLabel.value)) {
        selectedLabel.value = projectLabels.value[0] ?? ''
      }
    }
  } catch {
    // non-blocking
  }
}

async function finalizeBbox(bbox: [number, number, number, number]) {
  const [xmin, ymin, xmax, ymax] = bbox
  const w = xmax - xmin
  const h = ymax - ymin

  // allow small boxes, but filter out accidental clicks
  const minSide = 0.002
  if (w < minSide || h < minSide) return

  await api.post(`/api/images/${imageId.value}/predict`, {
    annotation_id: null,
    label: selectedLabel.value,
    bbox,
  })
}

function setBoxMode() {
  interactionMode.value = 'bbox'
  activeAnnotationId.value = null
  correctionPoints.value = []
  drawing.mode = 'idle'
  drawing.moved = false
  drawing.pointerId = null
}

function togglePointEditing(annotationId: number) {
  if (interactionMode.value === 'points' && activeAnnotationId.value === annotationId) {
    setBoxMode()
    return
  }
  interactionMode.value = 'points'
  activeAnnotationId.value = annotationId
  correctionPoints.value = []
  error.value = ''
}

function clearCorrectionPoints() {
  correctionPoints.value = []
}

async function confirmAnnotation(annotationId: number) {
  error.value = ''
  try {
    await api.patch(`/api/annotations/${annotationId}/confirm`)
    await fetchImageAndAnnotations()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  }
}

async function submitPointCorrection(ev: PointerEvent) {
  if (!activeAnnotation.value) {
    error.value = 'Select an annotation first before using point correction.'
    return
  }

  const pointLabel: 0 | 1 = ev.button === 2 ? 0 : 1
  const point = { ...pointToNorm(ev), label: pointLabel }
  correctionPoints.value = [...correctionPoints.value, point]
  error.value = ''

  try {
    await api.post(`/api/images/${imageId.value}/predict`, {
      annotation_id: activeAnnotation.value.id,
      points: [point],
    })
    await fetchImageAndAnnotations()
  } catch (err: any) {
    correctionPoints.value = correctionPoints.value.slice(0, -1)
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  }
}

function onPointerDown(ev: PointerEvent) {
  if (interactionMode.value === 'points') {
    if (!canPointCorrect.value) return
    if (ev.button !== 0 && ev.button !== 2) return
    ev.preventDefault()
    ev.stopPropagation()
    void submitPointCorrection(ev)
    return
  }

  if (!canDraw.value) return
  if (ev.button !== 0) return
  ev.preventDefault()
  ev.stopPropagation()

  if (!selectedLabel.value) return
  error.value = ''

  const p = pointToNorm(ev)

  // second click: finalize in "armed" mode
  if (drawing.mode === 'armed') {
    drawing.curX = p.x
    drawing.curY = p.y
    const bbox = draftBbox.value
    drawing.mode = 'idle'
    drawing.moved = false
    drawing.pointerId = null
    if (bbox) {
      void (async () => {
        try {
          await finalizeBbox(bbox)
          await fetchImageAndAnnotations()
        } catch (err: any) {
          error.value = err?.response?.data?.message
            ? String(err.response.data.message)
            : err?.message
              ? String(err.message)
              : String(err)
        }
      })()
    }
    return
  }

  // first click: start dragging
  drawing.mode = 'dragging'
  drawing.moved = false
  drawing.pointerId = ev.pointerId
  drawing.startX = p.x
  drawing.startY = p.y
  drawing.curX = p.x
  drawing.curY = p.y
  stageRef.value?.setPointerCapture?.(ev.pointerId)
}

function onPointerMove(ev: PointerEvent) {
  if (drawing.mode === 'idle') return
  const p = pointToNorm(ev)
  if (drawing.mode === 'dragging') {
    const dx = Math.abs(p.x - drawing.startX)
    const dy = Math.abs(p.y - drawing.startY)
    if (dx > 0.001 || dy > 0.001) drawing.moved = true
  }
  drawing.curX = p.x
  drawing.curY = p.y
}

async function onPointerUp(ev: PointerEvent) {
  if (drawing.mode !== 'dragging') return
  ev.preventDefault()
  ev.stopPropagation()

  const capturedPointerId = drawing.pointerId ?? ev.pointerId
  try {
    const bbox = draftBbox.value
    const moved = drawing.moved

    // Stop "dragging" first, so draft box doesn't flash.
    drawing.mode = 'idle'
    drawing.moved = false

    // If it was a click (not moved), switch to "armed" mode for click-click drawing.
    if (!moved) {
      drawing.mode = 'armed'
      return
    }

    if (!bbox) return
    await finalizeBbox(bbox)
    await fetchImageAndAnnotations()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    try {
      stageRef.value?.releasePointerCapture?.(capturedPointerId)
    } catch {
      // ignore
    }
    drawing.pointerId = null
  }
}

function onPointerCancel(ev: PointerEvent) {
  if (drawing.mode === 'idle') return
  ev.preventDefault()
  ev.stopPropagation()
  if (drawing.pointerId != null) {
    try {
      stageRef.value?.releasePointerCapture?.(drawing.pointerId)
    } catch {
      // ignore
    }
  }
  drawing.mode = 'idle'
  drawing.moved = false
  drawing.pointerId = null
}

function onKeyDown(ev: KeyboardEvent) {
  if (ev.key !== 'Escape') return
  if (drawing.mode !== 'idle') {
    drawing.mode = 'idle'
    drawing.moved = false
    drawing.pointerId = null
    return
  }
  if (correctionPoints.value.length > 0) {
    correctionPoints.value = []
    return
  }
  if (interactionMode.value === 'points') {
    setBoxMode()
  }
}

async function deleteAnnotation(annotationId: number) {
  if (!confirm(`Delete annotation #${annotationId}?`)) return
  error.value = ''
  try {
    await api.delete(`/api/annotations/${annotationId}`)
    if (activeAnnotationId.value === annotationId) {
      setBoxMode()
    }
    await fetchImageAndAnnotations()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  }
}

function goDev() {
  router.push({ name: 'dev' })
}

onMounted(() => {
  void fetchImageAndAnnotations()
  void fetchProjectSettings()
  resizeObserver = new ResizeObserver(() => updateStageSize())
  if (stageRef.value) {
    resizeObserver.observe(stageRef.value)
    updateStageSize()
  }
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('keydown', onKeyDown)
})

watch(imageId, () => {
  void fetchImageAndAnnotations()
})

watch(projectId, () => {
  void fetchProjectSettings()
})

watch(stageRef, (el, prevEl) => {
  if (!resizeObserver) return
  if (prevEl) resizeObserver.unobserve(prevEl)
  if (el) {
    resizeObserver.observe(el)
    updateStageSize()
  }
})

watch(
  () => drawing.mode,
  (m) => {
    // Clear transient errors when user re-enters drawing.
    if (m !== 'idle') error.value = ''
  }
)
</script>

<template>
  <section class="wrap">
    <header class="header">
      <div>
        <h1>标注（bbox）</h1>
        <div class="sub">
          Project #{{ projectId }} · Image #{{ imageId }} · 单击一次开始/单击一次结束（也支持按住拖拽）· Esc 取消
        </div>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" @click="back">返回列表</button>
        <button class="btn" type="button" :disabled="loading" @click="fetchImageAndAnnotations">刷新</button>
        <button class="btn" type="button" @click="goDev">Dev</button>
      </div>
    </header>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="controls card">
      <div class="row">
        <label class="label">label</label>
        <select v-model="selectedLabel" class="input" data-testid="detail-label-select" :disabled="projectLabels.length === 0">
          <option v-for="l in projectLabels" :key="l" :value="l">{{ l }}</option>
        </select>
        <div v-if="projectLabels.length === 0" class="inline-warn">
          请先在项目“图片列表”页配置 labels
        </div>
      </div>
      <div class="row">
        <label class="label">mode</label>
        <div class="mode-actions">
          <button
            class="btn small"
            data-testid="box-mode-btn"
            type="button"
            :class="{ primary: interactionMode === 'bbox' }"
            @click="setBoxMode"
          >
            Box Mode
          </button>
          <button
            class="btn small"
            data-testid="clear-points-btn"
            type="button"
            :disabled="correctionPoints.length === 0"
            @click="clearCorrectionPoints"
          >
            Clear Points
          </button>
        </div>
      </div>
      <div v-if="interactionMode === 'points'" class="hint">
        Point mode: left click adds a positive point, right click adds a negative point. Active annotation:
        {{ activeAnnotationId ?? '-' }}
      </div>
      <div class="hint">
        本系统不接收用户自然语言提示词；自动标注使用固定系统提示词 + labels 列表做 grounding。批量自动标注请在“图片列表”页触发。
      </div>
    </div>

    <div class="stage card">
      <div v-if="!image" class="hint">图片信息加载中…</div>
      <div
        v-else
        ref="stageRef"
        class="stage-inner"
        data-testid="annotation-stage"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerCancel"
        @contextmenu.prevent
      >
        <img class="img" :src="fileSrc()" :alt="image.filename" draggable="false" @dragstart.prevent />
        <svg class="overlay" :viewBox="viewBox()" preserveAspectRatio="xMinYMin meet">
          <g v-for="a in annotations" :key="a.id">
            <polygon
              v-if="a.polygon && a.polygon.length >= 3"
              :points="polygonPoints(a.polygon)"
              class="polygon"
              :class="{ 'polygon-active': activeAnnotationId === a.id }"
              vector-effect="non-scaling-stroke"
            />
            <template v-if="a.bbox">
              <rect
                :x="rectPx(a.bbox).x"
                :y="rectPx(a.bbox).y"
                :width="rectPx(a.bbox).width"
                :height="rectPx(a.bbox).height"
                class="bbox"
                :class="{ 'bbox-active': activeAnnotationId === a.id }"
                vector-effect="non-scaling-stroke"
              />
              <text
                :x="rectPx(a.bbox).x + labelOffsetX"
                :y="rectPx(a.bbox).y + labelOffsetY"
                :font-size="labelFontSize"
                class="label-text"
              >
                {{ a.label }}
              </text>
            </template>
          </g>
          <g v-for="(point, idx) in correctionPoints" :key="`point-${idx}`">
            <circle
              :cx="pointPx(point).cx"
              :cy="pointPx(point).cy"
              :r="pointRadius"
              :class="point.label === 1 ? 'point-positive' : 'point-negative'"
            />
          </g>

          <template v-if="draftBbox && image?.width && image?.height">
            <rect
              :x="rectPx(draftBbox).x"
              :y="rectPx(draftBbox).y"
              :width="rectPx(draftBbox).width"
              :height="rectPx(draftBbox).height"
              class="draft"
              vector-effect="non-scaling-stroke"
            />
          </template>
        </svg>
      </div>
    </div>

    <div class="card">
      <h2 class="h2">标注列表</h2>
      <div v-if="annotations.length === 0" class="hint">暂无标注：单击两次或拖拽画框创建一个。</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Label</th>
            <th>Bbox(0..1)</th>
            <th>Polygon</th>
            <th>Source</th>
            <th>Confirmed</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in annotations" :key="a.id">
            <td class="mono">{{ a.id }}</td>
            <td class="mono">{{ a.label }}</td>
            <td class="mono">{{ a.bbox }}</td>
            <td class="mono">{{ a.polygon ? `${a.polygon.length} pts` : '-' }}</td>
            <td class="mono">{{ a.source }}</td>
            <td class="mono">{{ a.is_confirmed }}</td>
            <td class="row-actions" :class="{ 'row-active': activeAnnotationId === a.id }">
              <button
                v-if="a.polygon"
                class="btn small"
                :class="{ primary: interactionMode === 'points' && activeAnnotationId === a.id }"
                :data-testid="`point-edit-${a.id}`"
                type="button"
                @click="togglePointEditing(a.id)"
              >
                {{ interactionMode === 'points' && activeAnnotationId === a.id ? 'Stop Points' : 'Point Edit' }}
              </button>
              <button
                class="btn small"
                :data-testid="`confirm-${a.id}`"
                type="button"
                :disabled="a.is_confirmed"
                @click="confirmAnnotation(a.id)"
              >
                {{ a.is_confirmed ? 'Confirmed' : 'Confirm' }}
              </button>
              <button class="btn danger small" :data-testid="`delete-${a.id}`" type="button" @click="deleteAnnotation(a.id)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.wrap {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.sub {
  opacity: 0.7;
  margin-top: 6px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  padding: 14px;
}

.controls .row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.mode-actions {
  display: flex;
  gap: 8px;
}

.label {
  width: 70px;
  opacity: 0.75;
}

.input {
  flex: 1;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(0, 0, 0, 0.15);
  color: inherit;
}

.inline-warn {
  opacity: 0.8;
  font-size: 12px;
  color: rgba(248, 81, 73, 0.95);
  white-space: nowrap;
}

.hint {
  margin-top: 10px;
  opacity: 0.75;
}

.stage-inner {
  position: relative;
  user-select: none;
  touch-action: none;
}

.img {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 10px;
}

.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.bbox {
  fill: rgba(0, 255, 0, 0.08);
  stroke: rgba(0, 255, 0, 0.9);
  stroke-width: 1;
}

.bbox-active {
  stroke: rgba(255, 214, 10, 0.98);
  stroke-width: 2;
}

.polygon {
  fill: rgba(255, 87, 34, 0.18);
  stroke: rgba(255, 132, 84, 0.92);
  stroke-width: 1.5;
}

.polygon-active {
  fill: rgba(255, 214, 10, 0.18);
  stroke: rgba(255, 214, 10, 0.98);
  stroke-width: 2;
}

.point-positive {
  fill: rgba(0, 200, 120, 0.92);
  stroke: rgba(255, 255, 255, 0.95);
  stroke-width: 1.5;
}

.point-negative {
  fill: rgba(248, 81, 73, 0.95);
  stroke: rgba(255, 255, 255, 0.95);
  stroke-width: 1.5;
}

.draft {
  fill: rgba(99, 102, 241, 0.12);
  stroke: rgba(99, 102, 241, 0.9);
  stroke-width: 1;
  stroke-dasharray: 6 4;
}

.label-text {
  fill: rgba(0, 255, 0, 0.95);
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.55);
  stroke-width: 2px;
}

.table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
}

.table th,
.table td {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px 10px;
  text-align: left;
  font-size: 13px;
}

.row-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.row-active {
  background: rgba(255, 214, 10, 0.06);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.h2 {
  margin: 0;
}

.btn {
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  padding: 8px 12px;
  border-radius: 10px;
}

.btn.small {
  padding: 6px 10px;
  border-radius: 9px;
  font-size: 12px;
}

.btn.primary {
  border-color: rgba(99, 102, 241, 0.55);
}

.btn.danger {
  border-color: rgba(248, 81, 73, 0.55);
}

.btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.error {
  color: rgba(248, 81, 73, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 13px;
}
</style>
