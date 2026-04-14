<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import MetricLineChart from '../../components/MetricLineChart.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useRunStore } from '../../stores/runStore'
import { taskStatusText } from '../../utils/uiText'

const route = useRoute()
const runStore = useRunStore()
const projectId = computed(() => Number(route.params.projectId))

const latestJob = computed(() => runStore.latestTrain)
const latestPoint = computed(() => {
  const metrics = latestJob.value?.metrics ?? []
  return metrics[metrics.length - 1] ?? null
})

const lossLabels = computed(() =>
  (latestJob.value?.metrics ?? []).map((point, index) => {
    if (point.step != null) return `S${point.step}`
    if (point.epoch != null) return `E${point.epoch}`
    return `#${index + 1}`
  }),
)

const lossSeries = computed(() => [
  {
    key: 'loss',
    label: 'Loss',
    color: '#0B5FFF',
    values: (latestJob.value?.metrics ?? []).map((point) => point.loss ?? 0),
    format: 'decimal' as const,
  },
])

onMounted(() => {
  if (Number.isFinite(projectId.value)) {
    void runStore.load(projectId.value)
  }
})

watch(projectId, (nextProjectId) => {
  if (Number.isFinite(nextProjectId)) {
    void runStore.load(nextProjectId)
  }
})

function statusTone(status: string): 'success' | 'accent' | 'danger' | 'neutral' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'RUNNING') return 'accent'
  if (status === 'FAILED') return 'danger'
  return 'neutral'
}
</script>

<template>
  <div class="train-page">
    <SectionPanel>
      <template #header><strong>微调</strong></template>
      <template #actions>
        <button class="primary" @click="runStore.startTrain">启动微调</button>
      </template>

      <div class="train-kpis">
        <div class="train-kpi">
          <span>最新模型</span>
          <strong class="mono">{{ latestJob?.modelTag ?? '--' }}</strong>
        </div>
        <div class="train-kpi">
          <span>最新 Loss</span>
          <strong class="mono">{{ latestPoint?.loss?.toFixed(4) ?? '--' }}</strong>
        </div>
        <div class="train-kpi">
          <span>轮次</span>
          <strong class="mono">{{ latestPoint?.epoch ?? '--' }}/{{ latestPoint?.epochTotal ?? '--' }}</strong>
        </div>
        <div class="train-kpi">
          <span>学习率</span>
          <strong class="mono">{{ latestPoint?.learningRate?.toFixed(6) ?? '--' }}</strong>
        </div>
      </div>

      <MetricLineChart :labels="lossLabels" :series="lossSeries" empty-label="暂无微调指标" />
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>微调任务</strong></template>
      <div class="train-stack">
        <div v-if="runStore.trainJobs.length === 0" class="train-empty">暂无微调任务</div>
        <button v-for="job in runStore.trainJobs" :key="job.id" class="train-row">
          <div class="train-row-main">
            <strong>{{ job.modelTag }}</strong>
            <StatusChip :label="taskStatusText(job.status)" :tone="statusTone(job.status)" />
          </div>
          <div class="train-row-grid mono">
            <span>开始={{ job.startedAt }}</span>
            <span>数据集={{ job.datasetPath }}</span>
            <span>{{ job.lossCurveLabel }}</span>
          </div>
          <div class="train-log mono">
            <div v-for="line in job.logExcerpt" :key="line">{{ line }}</div>
          </div>
        </button>
      </div>
    </SectionPanel>
  </div>
</template>

<style scoped>
.train-page {
  display: grid;
  gap: 16px;
}

.train-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.train-kpi {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px 16px;
}

.train-kpi span {
  color: var(--text-muted);
  font-size: 13px;
}

.train-kpi strong {
  font-size: 20px;
}

.train-stack {
  display: grid;
  gap: 12px;
}

.train-empty {
  color: var(--text-muted);
}

.train-row {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px;
  text-align: left;
}

.train-row-main {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.train-row-grid {
  display: grid;
  gap: 6px;
  color: var(--text-muted);
}

.train-log {
  display: grid;
  gap: 6px;
  border-top: 1px solid var(--line);
  padding-top: 10px;
  color: var(--text-muted);
}

@media (max-width: 1080px) {
  .train-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .train-kpis {
    grid-template-columns: 1fr;
  }
}
</style>
