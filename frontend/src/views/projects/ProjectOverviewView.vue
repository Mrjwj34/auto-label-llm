<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SectionPanel from '../../components/SectionPanel.vue'
import TaskBanner from '../../components/TaskBanner.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useDatasetStore } from '../../stores/datasetStore'
import { useRunStore } from '../../stores/runStore'
import { taskStatusText } from '../../utils/uiText'

const route = useRoute()
const router = useRouter()
const datasetStore = useDatasetStore()
const runStore = useRunStore()

const projectId = computed(() => Number(route.params.projectId))
const workspace = computed(() => datasetStore.workspace)
const latestTrainPoint = computed(() => {
  const metrics = runStore.latestTrain?.metrics ?? []
  return metrics[metrics.length - 1] ?? null
})

async function hydrate(projectValue: number) {
  await Promise.all([datasetStore.load(projectValue), runStore.load(projectValue)])
}

onMounted(() => {
  if (Number.isFinite(projectId.value)) {
    void hydrate(projectId.value)
  }
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
    <TaskBanner v-if="workspace" :task="workspace.task" class="project-view-wide" />

    <div class="project-kpis project-view-wide">
      <div class="project-kpi"><span>图片数</span><strong class="mono">{{ workspace?.summary.imageCount ?? 0 }}</strong></div>
      <div class="project-kpi"><span>待复核</span><strong class="mono">{{ workspace?.summary.reviewCount ?? 0 }}</strong></div>
      <div class="project-kpi"><span>模型标签</span><strong class="mono">{{ workspace?.activeModelTag ?? '-' }}</strong></div>
      <div class="project-kpi"><span>Dice</span><strong class="mono">{{ workspace?.latestEvaluationDice?.toFixed(2) ?? '--' }}</strong></div>
    </div>

    <SectionPanel>
      <template #header><strong>待复核队列</strong></template>
      <div class="overview-list">
        <button
          v-for="item in workspace?.reviewQueue ?? []"
          :key="item.imageId"
          class="overview-row"
          @click="openAnnotate(item.imageId)"
        >
          <span class="mono">#{{ item.imageId }}</span>
          <strong>{{ item.filename }}</strong>
          <span class="mono">质量={{ item.qualityScore?.toFixed(2) ?? '--' }}</span>
          <span class="mono">标注={{ item.annotationCount }}</span>
        </button>
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>微调</strong></template>
      <div class="overview-stack">
        <div class="mono">最近模型标签={{ runStore.latestTrain?.modelTag ?? '--' }}</div>
        <div class="mono">loss={{ latestTrainPoint?.loss?.toFixed(4) ?? '--' }}</div>
        <div class="mono">轮次={{ latestTrainPoint?.epoch ?? '--' }}/{{ latestTrainPoint?.epochTotal ?? '--' }}</div>
        <div class="mono">{{ runStore.latestTrain?.lossCurveLabel ?? '曲线=等待中' }}</div>
        <StatusChip :label="taskStatusText(runStore.latestTrain?.status ?? 'IDLE')" :tone="runStore.latestTrain?.status === 'SUCCESS' ? 'success' : 'neutral'" />
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>评估</strong></template>
      <div class="overview-stack">
        <div class="mono">最近模型标签={{ runStore.latestEvaluation?.modelTag ?? '--' }}</div>
        <div class="mono">f1={{ runStore.latestEvaluation?.f1?.toFixed(2) ?? '--' }}</div>
        <div class="mono">dice={{ runStore.latestEvaluation?.dice?.toFixed(2) ?? '--' }}</div>
      </div>
    </SectionPanel>
  </div>
</template>

<style scoped>
.project-view-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 16px;
}

.project-view-wide {
  grid-column: 1 / -1;
}

.project-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.project-kpi {
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px;
}

.project-kpi span {
  display: block;
  color: var(--text-muted);
  font-size: 13px;
}

.project-kpi strong {
  display: block;
  margin-top: 10px;
  font-size: 24px;
}

.overview-list,
.overview-stack {
  display: grid;
  gap: 10px;
}

.overview-row {
  display: grid;
  grid-template-columns: 0.5fr 1.3fr 1fr 1fr;
  gap: 14px;
  background: var(--panel-soft);
  text-align: left;
}

@media (max-width: 1080px) {
  .project-view-grid {
    grid-template-columns: 1fr;
  }

  .project-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
