<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import MetricLineChart from '../../components/MetricLineChart.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useRunStore } from '../../stores/runStore'
import { splitText, taskStatusText } from '../../utils/uiText'

const route = useRoute()
const runStore = useRunStore()
const projectId = computed(() => Number(route.params.projectId))

const latestRun = computed(() => runStore.latestEvaluation)
const previousRun = computed(() => runStore.evaluations[1] ?? null)
const historyRuns = computed(() => [...runStore.evaluations].reverse())

const trendLabels = computed(() => historyRuns.value.map((run) => `#${run.id}`))
const trendSeries = computed(() => [
  {
    key: 'f1',
    label: 'F1',
    color: '#0B5FFF',
    values: historyRuns.value.map((run) => run.f1),
    format: 'percent' as const,
  },
  {
    key: 'dice',
    label: 'Dice',
    color: '#58A6FF',
    values: historyRuns.value.map((run) => run.dice),
    format: 'percent' as const,
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

function deltaText(current: number | undefined, previous: number | undefined): string {
  if (current == null || previous == null) return '--'
  const delta = current - previous
  const sign = delta > 0 ? '+' : ''
  return `${sign}${delta.toFixed(2)}`
}
</script>

<template>
  <div class="evaluate-page">
    <SectionPanel>
      <template #header><strong>评估</strong></template>
      <template #actions>
        <button class="primary" @click="runStore.startEvaluation">开始评估</button>
      </template>

      <div class="evaluate-kpis">
        <div class="evaluate-kpi">
          <span>最新 F1</span>
          <strong class="mono">{{ latestRun?.f1?.toFixed(2) ?? '--' }}</strong>
          <small class="mono">较上次 {{ deltaText(latestRun?.f1, previousRun?.f1) }}</small>
        </div>
        <div class="evaluate-kpi">
          <span>最新 Dice</span>
          <strong class="mono">{{ latestRun?.dice?.toFixed(2) ?? '--' }}</strong>
          <small class="mono">较上次 {{ deltaText(latestRun?.dice, previousRun?.dice) }}</small>
        </div>
        <div class="evaluate-kpi">
          <span>平均时延</span>
          <strong class="mono">{{ latestRun?.avgTotalMs ?? '--' }}</strong>
          <small class="mono">ms / image</small>
        </div>
        <div class="evaluate-kpi">
          <span>Fallback 图片</span>
          <strong class="mono">{{ latestRun?.fallbackImages ?? '--' }}</strong>
          <small class="mono">split={{ splitText(latestRun?.split ?? 'val') }}</small>
        </div>
      </div>

      <MetricLineChart :labels="trendLabels" :series="trendSeries" empty-label="暂无评估指标" />
    </SectionPanel>

    <div class="evaluate-grid">
      <SectionPanel>
        <template #header><strong>评估记录</strong></template>
        <div class="evaluate-stack">
          <div v-if="runStore.evaluations.length === 0" class="evaluate-empty">暂无评估记录</div>
          <button v-for="run in runStore.evaluations" :key="run.id" class="evaluate-row">
            <div class="evaluate-row-head">
              <strong>#{{ run.id }}</strong>
              <StatusChip :label="taskStatusText(run.status)" :tone="statusTone(run.status)" />
            </div>
            <div class="evaluate-row-grid mono">
              <span>创建={{ run.createdAt }}</span>
              <span>版本={{ run.modelTag }}</span>
              <span>split={{ splitText(run.split) }}</span>
              <span>F1={{ run.f1.toFixed(2) }}</span>
              <span>Dice={{ run.dice.toFixed(2) }}</span>
              <span>框 mIoU={{ run.miouBBox.toFixed(2) }}</span>
              <span>掩码 mIoU={{ run.miouMask.toFixed(2) }}</span>
              <span>Precision={{ run.precision.toFixed(2) }}</span>
              <span>Recall={{ run.recall.toFixed(2) }}</span>
            </div>
          </button>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>失败样本</strong></template>
        <div class="evaluate-stack">
          <div v-if="runStore.failureSamples.length === 0" class="evaluate-empty">暂无失败样本</div>
          <button v-for="sample in runStore.failureSamples" :key="sample.imageId" class="evaluate-row">
            <div class="evaluate-row-head">
              <strong>{{ sample.filename }}</strong>
              <StatusChip label="失败" tone="danger" />
            </div>
            <div class="evaluate-row-grid mono">
              <span>imageId={{ sample.imageId }}</span>
              <span>fp={{ sample.fp }}</span>
              <span>fn={{ sample.fn }}</span>
              <span>F1={{ sample.f1.toFixed(2) }}</span>
            </div>
          </button>
        </div>
      </SectionPanel>
    </div>
  </div>
</template>

<style scoped>
.evaluate-page {
  display: grid;
  gap: 16px;
}

.evaluate-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.evaluate-kpi {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px 16px;
}

.evaluate-kpi span,
.evaluate-kpi small {
  color: var(--text-muted);
}

.evaluate-kpi strong {
  font-size: 20px;
}

.evaluate-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.evaluate-stack {
  display: grid;
  gap: 12px;
}

.evaluate-empty {
  color: var(--text-muted);
}

.evaluate-row {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px;
  text-align: left;
}

.evaluate-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.evaluate-row-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 14px;
  color: var(--text-muted);
}

@media (max-width: 1080px) {
  .evaluate-kpis,
  .evaluate-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .evaluate-kpis,
  .evaluate-grid,
  .evaluate-row-grid {
    grid-template-columns: 1fr;
  }
}
</style>
