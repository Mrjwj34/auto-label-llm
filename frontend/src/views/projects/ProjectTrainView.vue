<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import MetricLineChart from '../../components/MetricLineChart.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useRunStore } from '../../stores/runStore'
import { taskStatusText } from '../../utils/uiText'

const route = useRoute()
const runStore = useRunStore()
const projectId = computed(() => Number(route.params.projectId))
const selectedJobId = ref<number | null>(null)

const selectedJob = computed(() => {
  if (selectedJobId.value == null) return runStore.latestTrain
  return runStore.trainJobs.find((job) => job.id === selectedJobId.value) ?? runStore.latestTrain
})

const latestPoint = computed(() => {
  const metrics = selectedJob.value?.metrics ?? []
  return metrics[metrics.length - 1] ?? null
})

const trainProgress = computed(() => {
  if (!selectedJob.value) return 0
  if (selectedJob.value.status === 'SUCCESS') return 100
  const epoch = latestPoint.value?.epoch ?? 0
  const epochTotal = latestPoint.value?.epochTotal ?? 0
  if (!epochTotal) return selectedJob.value.status === 'RUNNING' ? 8 : 0
  return Math.max(8, Math.min(96, Math.round((epoch / epochTotal) * 100)))
})

const lossLabels = computed(() =>
  (selectedJob.value?.metrics ?? []).map((point, index) => {
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
    values: (selectedJob.value?.metrics ?? []).map((point) => point.loss ?? 0),
    format: 'decimal' as const,
  },
])

const configRows = computed(() => {
  const config = selectedJob.value?.config ?? {}
  return [
    { label: '训练轮次', value: config.num_train_epochs ?? '--' },
    { label: '学习率', value: config.learning_rate ?? '--' },
    { label: 'Batch', value: config.per_device_train_batch_size ?? '--' },
    { label: '梯度累计', value: config.gradient_accumulation_steps ?? '--' },
    { label: 'Logging Steps', value: config.logging_steps ?? '--' },
    { label: '训练数据集', value: config.dataset ?? selectedJob.value?.datasetPath ?? '--' },
  ]
})

const logText = computed(() => {
  const lines = selectedJob.value?.logExcerpt ?? []
  return lines.length ? lines.join('\n') : '暂无日志'
})

const hasRunningJob = computed(() => runStore.trainJobs.some((job) => job.status === 'RUNNING' || job.status === 'QUEUED'))

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

watch(
  () => runStore.trainJobs,
  (jobs) => {
    if (!jobs.length) {
      selectedJobId.value = null
      return
    }
    if (selectedJobId.value == null || !jobs.some((job) => job.id === selectedJobId.value)) {
      selectedJobId.value = jobs[0]?.id ?? null
    }
  },
  { deep: true, immediate: true },
)

function statusTone(status: string): 'success' | 'accent' | 'danger' | 'neutral' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'RUNNING' || status === 'QUEUED') return 'accent'
  if (status === 'FAILED') return 'danger'
  return 'neutral'
}
</script>

<template>
  <div class="train-page">
    <SectionPanel>
      <template #header><strong>微调</strong></template>
      <template #actions>
        <button class="primary" :disabled="hasRunningJob" @click="runStore.startTrain">启动微调</button>
      </template>

      <div class="train-grid">
        <div class="train-main">
          <div class="train-summary">
            <div class="train-metric">
              <span>版本</span>
              <strong class="mono">{{ selectedJob?.modelTag ?? '--' }}</strong>
            </div>
            <div class="train-metric">
              <span>状态</span>
              <StatusChip :label="taskStatusText(selectedJob?.status ?? 'IDLE')" :tone="statusTone(selectedJob?.status ?? 'IDLE')" />
            </div>
            <div class="train-metric">
              <span>Loss</span>
              <strong class="mono">{{ latestPoint?.loss?.toFixed(4) ?? '--' }}</strong>
            </div>
            <div class="train-metric">
              <span>学习率</span>
              <strong class="mono">{{ latestPoint?.learningRate?.toFixed(6) ?? '--' }}</strong>
            </div>
            <div class="train-metric">
              <span>步数</span>
              <strong class="mono">{{ latestPoint?.step ?? '--' }}</strong>
            </div>
          </div>

          <div class="train-progress">
            <div class="train-progress-head mono">
              <span>进度</span>
              <span>{{ trainProgress }}%</span>
            </div>
            <div class="train-progress-track">
              <div class="train-progress-fill" :style="{ width: `${trainProgress}%` }" />
            </div>
          </div>

          <MetricLineChart :labels="lossLabels" :series="lossSeries" empty-label="暂无微调指标" />
        </div>

        <aside class="train-side">
          <div class="train-side-block">
            <strong>训练参数</strong>
            <div class="train-config-grid">
              <div v-for="row in configRows" :key="row.label" class="train-config-row">
                <span>{{ row.label }}</span>
                <strong class="mono">{{ row.value }}</strong>
              </div>
            </div>
          </div>

          <div class="train-side-block">
            <div class="train-side-head">
              <strong>日志</strong>
              <span class="train-side-caption mono">{{ selectedJob?.taskId ?? '--' }}</span>
            </div>
            <div class="train-log-path mono">{{ selectedJob?.logPath ?? '--' }}</div>
            <pre class="train-log mono">{{ logText }}</pre>
          </div>
        </aside>
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>微调任务</strong></template>
      <div v-if="runStore.trainJobs.length === 0" class="train-empty">暂无微调任务</div>
      <div v-else class="train-job-list">
        <button
          v-for="job in runStore.trainJobs"
          :key="job.id"
          class="train-job-row"
          :class="{ active: job.id === selectedJobId }"
          @click="selectedJobId = job.id"
        >
          <div class="train-job-head">
            <strong>{{ job.modelTag }}</strong>
            <StatusChip :label="taskStatusText(job.status)" :tone="statusTone(job.status)" />
          </div>
          <div class="train-job-meta mono">
            <span>开始={{ job.startedAt }}</span>
            <span>数据集={{ job.datasetPath }}</span>
            <span>{{ job.lossCurveLabel }}</span>
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

.train-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
}

.train-main,
.train-side,
.train-side-block,
.train-job-list {
  display: grid;
  gap: 12px;
}

.train-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.train-metric {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px 14px;
}

.train-metric span,
.train-config-row span,
.train-log-path {
  color: var(--text-muted);
  font-size: 12px;
}

.train-progress {
  display: grid;
  gap: 8px;
}

.train-progress-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-muted);
  font-size: 12px;
}

.train-progress-track {
  height: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
}

.train-progress-fill {
  height: 100%;
  background: var(--accent);
}

.train-side-block {
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px;
}

.train-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.train-side-caption {
  color: var(--text-muted);
  font-size: 12px;
}

.train-config-grid {
  display: grid;
  gap: 8px;
}

.train-config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}

.train-config-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.train-log {
  margin: 0;
  min-height: 240px;
  overflow: auto;
  border: 1px solid var(--line);
  background: #f9fbff;
  padding: 12px;
  color: var(--text-soft);
  white-space: pre-wrap;
}

.train-empty {
  color: var(--text-muted);
}

.train-job-row {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px;
  text-align: left;
}

.train-job-row.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.train-job-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.train-job-meta {
  display: grid;
  gap: 6px;
  color: var(--text-muted);
}

@media (max-width: 1200px) {
  .train-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .train-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .train-summary {
    grid-template-columns: 1fr;
  }
}
</style>
