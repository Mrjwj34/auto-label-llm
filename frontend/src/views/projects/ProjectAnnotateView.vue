<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SectionPanel from '../../components/SectionPanel.vue'
import { useAnnotationStudioStore } from '../../stores/annotationStudioStore'
import { useProjectStore } from '../../stores/projectStore'

type DrawMode = 'idle' | 'dragging' | 'armed'

const route = useRoute()
const router = useRouter()
const studioStore = useAnnotationStudioStore()
const projectStore = useProjectStore()

const projectId = computed(() => Number(route.params.projectId))
const imageId = computed(() => {
  const value = Number(route.query.imageId)
  return Number.isFinite(value) && value > 0 ? value : undefined
})

const selectedLabel = ref('')
const error = ref('')
const stageViewportRef = ref<HTMLDivElement | null>(null)
const stageRef = ref<HTMLDivElement | null>(null)
const stageViewportSize = reactive({ width: 0, height: 0 })
const stageSize = reactive({ width: 0, height: 0 })

const drawing = reactive({
  mode: 'idle' as DrawMode,
  startX: 0,
  startY: 0,
  curX: 0,
  curY: 0,
  pointerId: null as number | null,
  moved: false,
})

let resizeObserver: ResizeObserver | null = null

const projectLabels = computed(() => projectStore.settings?.labels ?? [])
const imageAnnotations = computed(() => studioStore.image?.annotations ?? [])
const hasAnnotations = computed(() => imageAnnotations.value.length > 0)
const currentQueueItem = computed(() => studioStore.queue.find((item) => item.imageId === studioStore.image?.id))
const selectedAnnotationId = computed({
  get: () => studioStore.selectedAnnotationId || 0,
  set: (value: number | string) => {
    const nextValue = Number(value)
    studioStore.selectAnnotation(Number.isFinite(nextValue) ? nextValue : 0)
  },
})
const stageCanvasStyle = computed(() => {
  const width = studioStore.image?.width ?? 16
  const height = studioStore.image?.height ?? 9
  const viewportWidth = stageViewportSize.width
  const viewportHeight = stageViewportSize.height

  if (!viewportWidth || !viewportHeight) {
    return {
      width: '100%',
      maxWidth: '100%',
      maxHeight: '100%',
      aspectRatio: `${width} / ${height}`,
    }
  }

  const scale = Math.min(viewportWidth / width, viewportHeight / height)

  return {
    width: `${Math.max(1, Math.floor(width * scale))}px`,
    height: `${Math.max(1, Math.floor(height * scale))}px`,
    aspectRatio: `${width} / ${height}`,
  }
})

const draftBbox = computed<[number, number, number, number] | null>(() => {
  if (drawing.mode === 'idle') return null
  const xmin = Math.min(drawing.startX, drawing.curX)
  const ymin = Math.min(drawing.startY, drawing.curY)
  const xmax = Math.max(drawing.startX, drawing.curX)
  const ymax = Math.max(drawing.startY, drawing.curY)
  return [xmin, ymin, xmax, ymax]
})

const labelFontSize = computed(() => Math.max(12, Math.min(34, userUnitsFromScreenPx(14))))
const labelOffsetX = computed(() => userUnitsFromScreenPx(8))
const labelOffsetY = computed(() => userUnitsFromScreenPx(18))

async function hydrate() {
  if (!Number.isFinite(projectId.value)) return
  await Promise.all([studioStore.load(projectId.value, imageId.value), projectStore.loadProject(projectId.value)])
}

function updateStageSize() {
  const stage = stageRef.value
  if (!stage) return
  const rect = stage.getBoundingClientRect()
  stageSize.width = rect.width
  stageSize.height = rect.height
}

function updateStageViewportSize() {
  const viewport = stageViewportRef.value
  if (!viewport) return
  const rect = viewport.getBoundingClientRect()
  stageViewportSize.width = rect.width
  stageViewportSize.height = rect.height
}

function openImage(nextImageId: number) {
  void router.replace(`/projects/${projectId.value}/annotate?imageId=${nextImageId}`)
}

function goPreviousImage() {
  const previousImageId = studioStore.previousImageId()
  if (previousImageId) {
    openImage(previousImageId)
  }
}

function goNextImage() {
  const nextImageId = studioStore.nextImageId()
  if (nextImageId) {
    openImage(nextImageId)
  }
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function pointToNorm(ev: PointerEvent): { x: number; y: number } {
  const stage = stageRef.value
  if (!stage) return { x: 0, y: 0 }
  const rect = stage.getBoundingClientRect()
  return {
    x: clamp01((ev.clientX - rect.left) / rect.width),
    y: clamp01((ev.clientY - rect.top) / rect.height),
  }
}

function userUnitsFromScreenPx(px: number): number {
  const imageWidth = studioStore.image?.width ?? 0
  if (!imageWidth) return px
  const stageWidth = stageSize.width || stageRef.value?.getBoundingClientRect().width || 0
  if (!stageWidth) return px
  const scale = stageWidth / imageWidth
  if (scale <= 0) return px
  return px / scale
}

function imageUnitsRect(bbox: [number, number, number, number] | null) {
  const width = studioStore.image?.width ?? 1
  const height = studioStore.image?.height ?? 1
  if (!bbox) return { x: 0, y: 0, width: 0, height: 0 }
  return {
    x: bbox[0] * width,
    y: bbox[1] * height,
    width: (bbox[2] - bbox[0]) * width,
    height: (bbox[3] - bbox[1]) * height,
  }
}

function polygonPoints(points: Array<[number, number]>) {
  const width = studioStore.image?.width ?? 1
  const height = studioStore.image?.height ?? 1
  return points.map(([x, y]) => `${x * width},${y * height}`).join(' ')
}

async function createDraftAnnotation(bbox: [number, number, number, number]) {
  error.value = ''
  await studioStore.createAnnotation(selectedLabel.value, bbox)
}

async function confirmSelected() {
  await studioStore.confirmSelected()
}

function annotationOptionText(annotationId: number): string {
  const annotation = imageAnnotations.value.find((item) => item.id === annotationId)
  if (!annotation) return `#${annotationId}`
  return `#${annotation.id} ${annotation.label}`
}

function resetDrawing() {
  if (drawing.pointerId != null) {
    try {
      stageRef.value?.releasePointerCapture?.(drawing.pointerId)
    } catch {
      // ignore
    }
  }
  drawing.mode = 'idle'
  drawing.pointerId = null
  drawing.moved = false
}

function onPointerDown(ev: PointerEvent) {
  if (!studioStore.image || !selectedLabel.value || ev.button !== 0) return
  ev.preventDefault()
  ev.stopPropagation()
  const point = pointToNorm(ev)

  if (drawing.mode === 'armed') {
    drawing.curX = point.x
    drawing.curY = point.y
    const bbox = draftBbox.value
    resetDrawing()
    if (!bbox) return
    void createDraftAnnotation(bbox).catch((reason: unknown) => {
      error.value = reason instanceof Error ? reason.message : String(reason)
    })
    return
  }

  drawing.mode = 'dragging'
  drawing.pointerId = ev.pointerId
  drawing.moved = false
  drawing.startX = point.x
  drawing.startY = point.y
  drawing.curX = point.x
  drawing.curY = point.y
  stageRef.value?.setPointerCapture?.(ev.pointerId)
}

function onPointerMove(ev: PointerEvent) {
  if (drawing.mode === 'idle') return
  const point = pointToNorm(ev)
  if (drawing.mode === 'dragging') {
    const dx = Math.abs(point.x - drawing.startX)
    const dy = Math.abs(point.y - drawing.startY)
    if (dx > 0.001 || dy > 0.001) {
      drawing.moved = true
    }
  }
  drawing.curX = point.x
  drawing.curY = point.y
}

async function onPointerUp(ev: PointerEvent) {
  if (drawing.mode !== 'dragging') return
  ev.preventDefault()
  ev.stopPropagation()
  const bbox = draftBbox.value
  const wasMoved = drawing.moved
  const pointerId = drawing.pointerId ?? ev.pointerId
  drawing.mode = 'idle'
  drawing.pointerId = null
  drawing.moved = false

  try {
    if (!wasMoved) {
      drawing.mode = 'armed'
      return
    }
    if (!bbox) return
    await createDraftAnnotation(bbox)
  } catch (reason: unknown) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    try {
      stageRef.value?.releasePointerCapture?.(pointerId)
    } catch {
      // ignore
    }
  }
}

function onPointerCancel(ev: PointerEvent) {
  if (drawing.mode === 'idle') return
  ev.preventDefault()
  ev.stopPropagation()
  resetDrawing()
}

function onKeyDown(ev: KeyboardEvent) {
  if (ev.key !== 'Escape') return
  if (drawing.mode !== 'idle') {
    resetDrawing()
  }
}

onMounted(() => {
  void hydrate()
  resizeObserver = new ResizeObserver(() => {
    updateStageViewportSize()
    updateStageSize()
  })
  if (stageViewportRef.value) {
    resizeObserver.observe(stageViewportRef.value)
    updateStageViewportSize()
  }
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

watch([projectId, imageId], () => {
  void hydrate()
})

watch(stageRef, (next, previous) => {
  if (!resizeObserver) return
  if (previous) resizeObserver.unobserve(previous)
  if (next) {
    resizeObserver.observe(next)
    updateStageSize()
  }
})

watch(stageViewportRef, (next, previous) => {
  if (!resizeObserver) return
  if (previous) resizeObserver.unobserve(previous)
  if (next) {
    resizeObserver.observe(next)
    updateStageViewportSize()
  }
})

watch(
  projectLabels,
  (labels) => {
    if (!labels.length) {
      selectedLabel.value = ''
      return
    }
    if (!selectedLabel.value || !labels.includes(selectedLabel.value)) {
      selectedLabel.value = labels[0] ?? ''
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="annotate-shell">
    <SectionPanel class="annotate-stage-panel">
      <template #header><strong>标注工作区</strong></template>
      <template #actions>
        <div class="annotate-toolbar">
          <select class="annotate-toolbar-select" v-model="selectedLabel" :disabled="projectLabels.length === 0">
            <option v-for="label in projectLabels" :key="label" :value="label">{{ label }}</option>
            <option v-if="projectLabels.length === 0" value="">未配置标签</option>
          </select>
          <button @click="hydrate">刷新</button>
          <button :disabled="!studioStore.previousImageId()" @click="goPreviousImage">上一张</button>
          <button :disabled="!studioStore.nextImageId()" @click="goNextImage">下一张</button>
          <button :disabled="!studioStore.selectedAnnotationId" @click="studioStore.deleteSelected">删除</button>
          <button class="primary" :disabled="!studioStore.selectedAnnotationId" @click="confirmSelected">确认</button>
        </div>
      </template>

      <div v-if="error" class="annotate-error">{{ error }}</div>

      <div v-if="studioStore.image" class="annotate-stage-wrap">
        <div ref="stageViewportRef" class="annotate-stage-viewport">
          <div
            ref="stageRef"
            class="annotate-stage"
            :style="stageCanvasStyle"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerCancel"
            @contextmenu.prevent
          >
            <img class="annotate-image" :src="studioStore.image.imageUrl" :alt="studioStore.image.filename" draggable="false" @dragstart.prevent />

            <svg class="annotate-overlay" :viewBox="`0 0 ${studioStore.image.width} ${studioStore.image.height}`" preserveAspectRatio="none">
              <g v-for="annotation in imageAnnotations" :key="annotation.id">
                <polygon
                  v-if="annotation.polygon.length"
                  :points="polygonPoints(annotation.polygon)"
                  class="annotate-polygon"
                  :class="{ active: studioStore.selectedAnnotationId === annotation.id }"
                />

                <template v-if="annotation.bbox">
                  <rect
                    :x="imageUnitsRect(annotation.bbox).x"
                    :y="imageUnitsRect(annotation.bbox).y"
                    :width="imageUnitsRect(annotation.bbox).width"
                    :height="imageUnitsRect(annotation.bbox).height"
                    class="annotate-bbox"
                    :class="{ active: studioStore.selectedAnnotationId === annotation.id }"
                  />

                  <text
                    :x="imageUnitsRect(annotation.bbox).x + labelOffsetX"
                    :y="imageUnitsRect(annotation.bbox).y + labelOffsetY"
                    :font-size="labelFontSize"
                    class="annotate-label"
                  >
                    {{ annotation.label }}
                  </text>
                </template>
              </g>

              <rect
                v-if="draftBbox"
                :x="imageUnitsRect(draftBbox).x"
                :y="imageUnitsRect(draftBbox).y"
                :width="imageUnitsRect(draftBbox).width"
                :height="imageUnitsRect(draftBbox).height"
                class="annotate-draft"
              />
            </svg>
          </div>
        </div>
      </div>

      <div v-else class="annotate-empty">没有可标注图片</div>
    </SectionPanel>

    <aside class="annotate-sidebar">
      <SectionPanel class="annotate-inspector-panel">
        <template #header><strong>当前图片</strong></template>
        <div class="annotate-inspector">
          <section class="annotate-inspector-section annotate-summary-section">
            <div class="annotate-focus-grid">
              <div class="annotate-focus-item">
                <span>待复核</span>
                <strong class="mono">{{ studioStore.queue.length }}</strong>
              </div>
              <div class="annotate-focus-item">
                <span>标注数</span>
                <strong class="mono">{{ imageAnnotations.length }}</strong>
              </div>
              <div class="annotate-focus-item">
                <span>质量分</span>
                <strong class="mono">{{ currentQueueItem?.qualityScore?.toFixed(2) ?? '--' }}</strong>
              </div>
            </div>
          </section>

          <section class="annotate-inspector-section annotate-queue-section">
            <div class="annotate-section-head">
              <strong>待复核队列</strong>
              <span class="mono">{{ studioStore.queue.length }}</span>
            </div>

            <div class="annotate-queue">
              <button
                v-for="item in studioStore.queue"
                :key="item.imageId"
                class="annotate-queue-item"
                :class="{ active: item.imageId === studioStore.image?.id }"
                @click="openImage(item.imageId)"
              >
                <strong>{{ item.filename }}</strong>
                <div class="annotate-queue-meta">
                  <span>质量={{ item.qualityScore?.toFixed(2) ?? '--' }}</span>
                  <span>数量={{ item.annotationCount }}</span>
                </div>
              </button>

              <div v-if="studioStore.queue.length === 0" class="annotate-empty">当前没有待复核图片</div>
            </div>
          </section>

          <section class="annotate-inspector-section">
            <div class="annotate-section-head">
              <strong>标注框</strong>
            </div>

            <div class="annotate-selection-panel">
              <select v-model.number="selectedAnnotationId" :disabled="!hasAnnotations">
                <option v-if="!hasAnnotations" :value="0">暂无标注框</option>
                <option v-for="annotation in imageAnnotations" :key="annotation.id" :value="annotation.id">
                  {{ annotationOptionText(annotation.id) }}
                </option>
              </select>

              <button :disabled="!studioStore.selectedAnnotationId" @click="studioStore.deleteSelected">删除框</button>
            </div>

            <div v-if="!hasAnnotations" class="annotate-empty">当前图片还没有标注框</div>
          </section>
        </div>
      </SectionPanel>
    </aside>
  </div>
</template>

<style scoped>
.annotate-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 272px;
  grid-template-rows: minmax(0, 1fr);
  gap: 10px;
  height: 100%;
  min-height: 100%;
  align-items: stretch;
}

.annotate-stage-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  height: 100%;
}

.annotate-stage-panel :deep(.section-panel-head) {
  align-items: flex-start;
  padding: 9px 10px;
}

.annotate-stage-panel :deep(.section-panel-body) {
  display: grid;
  gap: 10px;
  height: 100%;
  min-height: 0;
  padding: 10px;
}

.annotate-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.annotate-toolbar button,
.annotate-toolbar select {
  height: 36px;
  padding: 8px 12px;
}

.annotate-toolbar-select {
  min-width: 96px;
}

.annotate-stage-wrap {
  display: grid;
  height: 100%;
  min-height: 0;
}

.annotate-stage-viewport {
  position: relative;
  display: grid;
  height: 100%;
  min-height: clamp(420px, calc(100dvh - 286px), 760px);
  place-items: center;
  overflow: hidden;
  border: 1px solid #d4e0ee;
  background: linear-gradient(180deg, #f6faff 0%, #ebf3fe 100%);
  padding: 10px;
}

.annotate-stage-viewport::before {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(11, 95, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(11, 95, 255, 0.04) 1px, transparent 1px);
  background-size: 24px 24px;
  opacity: 0.7;
  animation: annotate-grid-drift 18s linear infinite;
  content: '';
}

.annotate-stage {
  position: relative;
  z-index: 1;
  max-width: 100%;
  max-height: 100%;
  border: 1px solid #b8cbe3;
  background: #dfe9f8;
  user-select: none;
  touch-action: none;
}

.annotate-image,
.annotate-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.annotate-image {
  display: block;
}

.annotate-overlay {
  pointer-events: none;
}

.annotate-bbox {
  fill: rgba(11, 95, 255, 0.12);
  stroke: #0b5fff;
  stroke-width: 3;
}

.annotate-bbox.active {
  stroke: #10233f;
}

.annotate-polygon {
  fill: rgba(11, 95, 255, 0.1);
  stroke: rgba(11, 95, 255, 0.72);
  stroke-width: 2;
}

.annotate-polygon.active {
  stroke: #10233f;
}

.annotate-draft {
  fill: rgba(11, 95, 255, 0.08);
  stroke: #0b5fff;
  stroke-width: 2;
  stroke-dasharray: 8 6;
}

.annotate-label {
  fill: #0b5fff;
  paint-order: stroke;
  stroke: rgba(255, 255, 255, 0.92);
  stroke-width: 3px;
  font-weight: 600;
}

.annotate-sidebar {
  min-width: 0;
  height: 100%;
}

.annotate-inspector-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  height: 100%;
}

.annotate-inspector-panel :deep(.section-panel-head) {
  padding: 9px 10px;
}

.annotate-inspector-panel :deep(.section-panel-body) {
  display: grid;
  height: 100%;
  min-height: 0;
  padding: 0;
}

.annotate-inspector {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  height: 100%;
  min-height: clamp(420px, calc(100dvh - 286px), 760px);
}

.annotate-inspector-section {
  display: grid;
  gap: 8px;
  padding: 10px;
}

.annotate-summary-section {
  padding-top: 8px;
}

.annotate-inspector-section + .annotate-inspector-section {
  border-top: 1px solid var(--line);
}

.annotate-queue-section {
  min-height: 0;
}

.annotate-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 22px;
}

.annotate-focus-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.annotate-focus-item {
  display: grid;
  gap: 3px;
  min-height: 58px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, #fbfdff 0%, #f3f8ff 100%);
  padding: 8px;
}

.annotate-focus-item span,
.annotate-queue-meta,
.annotate-empty {
  color: var(--text-muted);
  font-size: 11px;
}

.annotate-focus-item strong {
  font-size: 22px;
  line-height: 1;
}

.annotate-queue {
  display: grid;
  gap: 6px;
  min-height: 0;
  overflow-y: auto;
}

.annotate-queue-item {
  display: grid;
  gap: 3px;
  min-height: 60px;
  align-content: start;
  border: 1px solid var(--line);
  background: #f8fbff;
  padding: 8px 10px;
  text-align: left;
  overflow: hidden;
  transition:
    border-color 180ms ease,
    background-color 180ms ease;
}

.annotate-queue-item:hover {
  border-color: #a9c2e4;
  background: #f3f8ff;
}

.annotate-queue-item.active {
  border-color: var(--accent);
  background: linear-gradient(90deg, rgba(11, 95, 255, 0.12) 0%, rgba(255, 255, 255, 1) 100%);
}

.annotate-queue-item strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.annotate-selection-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 82px;
  gap: 6px;
}

.annotate-selection-panel select,
.annotate-selection-panel button {
  height: 36px;
}

.annotate-error {
  border: 1px solid rgba(212, 72, 72, 0.32);
  background: #fff4f4;
  padding: 8px 10px;
  color: var(--danger);
}

.annotate-empty {
  align-self: start;
}

@keyframes annotate-grid-drift {
  from {
    transform: translate3d(0, 0, 0);
  }

  to {
    transform: translate3d(24px, 24px, 0);
  }
}

@media (max-width: 1280px) {
  .annotate-shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
    height: auto;
  }

  .annotate-stage-viewport {
    height: auto;
    min-height: clamp(420px, calc(100dvh - 324px), 720px);
  }

  .annotate-inspector {
    height: auto;
    min-height: 0;
  }
}

@media (max-width: 960px) {
  .annotate-stage-panel :deep(.section-panel-head) {
    flex-direction: column;
    align-items: stretch;
  }

  .annotate-stage-panel :deep(.section-panel-actions) {
    width: 100%;
  }

  .annotate-toolbar {
    justify-content: stretch;
  }

  .annotate-toolbar > * {
    flex: 1 1 calc(50% - 3px);
  }

  .annotate-focus-grid {
    grid-template-columns: 1fr;
  }

  .annotate-selection-panel {
    grid-template-columns: 1fr;
  }

  .annotate-stage-viewport {
    height: auto;
    min-height: 360px;
  }
}
</style>
