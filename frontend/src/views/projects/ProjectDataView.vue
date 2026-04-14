<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SectionPanel from '../../components/SectionPanel.vue'
import TaskBanner from '../../components/TaskBanner.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useDatasetStore } from '../../stores/datasetStore'
import { imageStatusText, reviewStateText, sortModeText, splitText } from '../../utils/uiText'

const route = useRoute()
const router = useRouter()
const datasetStore = useDatasetStore()

const projectId = computed(() => Number(route.params.projectId))
const workspace = computed(() => datasetStore.workspace)

async function hydrate(nextProjectId: number) {
  await datasetStore.load(nextProjectId)
}

onMounted(() => {
  if (Number.isFinite(projectId.value)) {
    void hydrate(projectId.value)
  }
})

onBeforeUnmount(() => {
  datasetStore.stopPolling()
})

watch(projectId, (nextProjectId) => {
  if (Number.isFinite(nextProjectId)) {
    void hydrate(nextProjectId)
  }
})

function openAnnotate(imageId: number) {
  void router.push(`/projects/${projectId.value}/annotate?imageId=${imageId}`)
}
</script>

<template>
  <div class="project-view-grid">
    <SectionPanel class="project-view-wide">
      <template #header><strong>数据操作</strong></template>
      <template #actions>
        <button class="primary">上传</button>
        <button @click="datasetStore.startBatchAnnotate">批量标注</button>
        <button>导入 ZIP</button>
        <button>导出 YOLO</button>
        <button>导出 COCO</button>
      </template>
      <div class="data-toolbar mono">
        <span>当前模型标签={{ workspace?.activeModelTag ?? '-' }}</span>
        <span>标签={{ workspace?.labels.join('、') ?? '-' }}</span>
      </div>
    </SectionPanel>

    <TaskBanner v-if="workspace" :task="workspace.task" class="project-view-wide" />

    <SectionPanel class="project-view-wide">
      <template #header><strong>图片</strong></template>
      <template #actions>
        <select v-model="datasetStore.sortMode">
          <option value="review_queue">{{ sortModeText('review_queue') }}</option>
          <option value="latest_quality">{{ sortModeText('latest_quality') }}</option>
          <option value="newest">{{ sortModeText('newest') }}</option>
        </select>
      </template>
      <transition-group name="grid" tag="div" class="data-grid">
        <button
          v-for="image in datasetStore.sortedImages"
          :key="image.id"
          class="data-card"
          @click="openAnnotate(image.id)"
        >
          <img class="data-thumb" :src="image.thumbnailUrl" :alt="image.filename" />
          <strong>{{ image.filename }}</strong>
          <div class="data-card-meta mono">状态={{ imageStatusText(image.status) }}</div>
          <div class="data-card-meta mono">质量={{ image.qualityScore?.toFixed(2) ?? '--' }}</div>
          <div class="data-card-meta mono">数据划分={{ splitText(image.split) }}</div>
          <StatusChip
            :label="reviewStateText(image.reviewState)"
            :tone="image.reviewState === 'review' ? 'warning' : image.reviewState === 'ok' ? 'success' : 'neutral'"
          />
        </button>
      </transition-group>
    </SectionPanel>
  </div>
</template>

<style scoped>
.project-view-grid {
  display: grid;
  gap: 16px;
}

.project-view-wide {
  grid-column: 1 / -1;
}

.data-toolbar {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  color: var(--text-muted);
  font-size: 13px;
}

.data-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.data-card {
  display: grid;
  gap: 10px;
  background: var(--panel-soft);
  text-align: left;
}

.data-thumb {
  width: 100%;
  border: 1px solid var(--line);
}

.data-card-meta {
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 1080px) {
  .data-grid {
    grid-template-columns: 1fr;
  }
}
</style>
