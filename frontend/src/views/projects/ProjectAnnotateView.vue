<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useAnnotationStudioStore } from '../../stores/annotationStudioStore'
import { annotationBackendText, sourceText } from '../../utils/uiText'

const route = useRoute()
const router = useRouter()
const studioStore = useAnnotationStudioStore()

const projectId = computed(() => Number(route.params.projectId))
const imageId = computed(() => {
  const value = Number(route.query.imageId)
  return Number.isFinite(value) && value > 0 ? value : undefined
})

async function hydrate() {
  if (Number.isFinite(projectId.value)) {
    await studioStore.load(projectId.value, imageId.value)
  }
}

onMounted(() => {
  void hydrate()
})

watch([projectId, imageId], () => {
  void hydrate()
})

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

async function confirmAndMaybeAdvance() {
  await studioStore.confirmSelected()
  const nextImageId = studioStore.nextImageId()
  if (nextImageId) {
    void router.replace(`/projects/${projectId.value}/annotate?imageId=${nextImageId}`)
  }
}
</script>

<template>
  <div class="annotate-layout">
    <SectionPanel>
      <template #header><strong>队列</strong></template>
      <div class="annotate-queue">
        <button
          v-for="item in studioStore.queue"
          :key="item.imageId"
          class="annotate-queue-item"
          :class="{ active: item.imageId === studioStore.image?.id }"
          @click="router.replace(`/projects/${projectId}/annotate?imageId=${item.imageId}`)"
        >
          <strong>{{ item.filename }}</strong>
          <span class="mono">质量={{ item.qualityScore?.toFixed(2) ?? '--' }}</span>
          <span class="mono">标注={{ item.annotationCount }}</span>
        </button>
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>画布</strong></template>
      <template #actions>
        <button class="primary" :class="{ secondary: studioStore.mode !== 'bbox' }" @click="studioStore.setMode('bbox')">框选</button>
        <button :disabled="!studioStore.supportsPointMode" :class="{ primary: studioStore.mode === 'point' }" @click="studioStore.setMode('point')">
          点修正
        </button>
      </template>
      <div v-if="studioStore.image" class="annotate-stage">
        <img class="annotate-image" :src="studioStore.image.imageUrl" :alt="studioStore.image.filename" />
        <svg class="annotate-overlay" :viewBox="`0 0 ${studioStore.image.width} ${studioStore.image.height}`" preserveAspectRatio="none">
          <g v-for="annotation in studioStore.image.annotations" :key="annotation.id">
            <polygon
              v-if="annotation.polygon.length"
              :points="polygonPoints(annotation.polygon)"
              class="annotate-polygon"
              :class="{ active: studioStore.selectedAnnotationId === annotation.id }"
            />
            <rect
              v-if="annotation.bbox"
              :x="imageUnitsRect(annotation.bbox).x"
              :y="imageUnitsRect(annotation.bbox).y"
              :width="imageUnitsRect(annotation.bbox).width"
              :height="imageUnitsRect(annotation.bbox).height"
              class="annotate-bbox"
              :class="{ active: studioStore.selectedAnnotationId === annotation.id }"
            />
          </g>
        </svg>
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>检查器</strong></template>
      <div v-if="studioStore.selectedAnnotation" class="annotate-inspector">
        <div class="annotate-field"><span>标签</span><strong>{{ studioStore.selectedAnnotation.label }}</strong></div>
        <div class="annotate-field"><span>来源</span><strong class="mono">{{ sourceText(studioStore.selectedAnnotation.source) }}</strong></div>
        <div class="annotate-field"><span>置信度</span><strong class="mono">{{ studioStore.selectedAnnotation.confidence?.toFixed(2) ?? '--' }}</strong></div>
        <div class="annotate-field"><span>已确认</span><strong class="mono">{{ studioStore.selectedAnnotation.confirmed ? '是' : '否' }}</strong></div>
        <div class="annotate-field"><span>后端</span><strong class="mono">{{ annotationBackendText(studioStore.selectedAnnotation.runtime.provider) }}</strong></div>
        <div class="annotate-field"><span>模型标签</span><strong class="mono">{{ studioStore.selectedAnnotation.runtime.modelTag }}</strong></div>
        <div class="annotate-field"><span>模型路由</span><strong class="mono">{{ studioStore.selectedAnnotation.runtime.modelName }}</strong></div>
        <div class="annotate-actions">
          <button @click="studioStore.deleteSelected">删除</button>
          <button class="primary" @click="confirmAndMaybeAdvance">确认</button>
        </div>
        <div class="annotate-list">
          <button
            v-for="annotation in studioStore.image?.annotations ?? []"
            :key="annotation.id"
            class="annotate-list-item"
            :class="{ active: annotation.id === studioStore.selectedAnnotationId }"
            @click="studioStore.selectAnnotation(annotation.id)"
          >
            <span class="mono">#{{ annotation.id }}</span>
            <span>{{ annotation.label }}</span>
            <StatusChip :label="annotation.confirmed ? '已确认' : sourceText(annotation.source)" :tone="annotation.confirmed ? 'success' : 'neutral'" />
          </button>
        </div>
      </div>
    </SectionPanel>
  </div>
</template>

<style scoped>
.annotate-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 320px;
  gap: 16px;
}

.annotate-queue,
.annotate-inspector,
.annotate-list {
  display: grid;
  gap: 10px;
}

.annotate-queue-item,
.annotate-list-item {
  display: grid;
  gap: 6px;
  background: var(--panel-soft);
  text-align: left;
}

.annotate-queue-item.active,
.annotate-list-item.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.annotate-stage {
  position: relative;
  min-height: 620px;
  border: 1px solid var(--line);
  background: #10233f;
}

.annotate-image,
.annotate-overlay {
  position: absolute;
  inset: 0;
  height: 100%;
  width: 100%;
}

.annotate-image {
  object-fit: cover;
}

.annotate-overlay {
  pointer-events: none;
}

.annotate-bbox {
  fill: rgba(11, 95, 255, 0.12);
  stroke: #8fc0ff;
  stroke-width: 3;
}

.annotate-bbox.active {
  stroke: #ffffff;
}

.annotate-polygon {
  fill: rgba(75, 163, 255, 0.18);
  stroke: #71b7ff;
  stroke-width: 3;
}

.annotate-polygon.active {
  stroke: #ffffff;
}

.annotate-field {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 10px;
}

.annotate-field span {
  color: var(--text-muted);
}

.annotate-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 1280px) {
  .annotate-layout {
    grid-template-columns: 1fr;
  }
}
</style>
