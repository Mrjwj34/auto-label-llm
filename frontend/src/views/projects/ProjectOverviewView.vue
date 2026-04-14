<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SectionPanel from '../../components/SectionPanel.vue'
import TaskBanner from '../../components/TaskBanner.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useDatasetStore } from '../../stores/datasetStore'
import { useRunStore } from '../../stores/runStore'
import { taskFamilyText, taskStatusText } from '../../utils/uiText'

const route = useRoute()
const router = useRouter()
const datasetStore = useDatasetStore()
const runStore = useRunStore()

const projectId = computed(() => Number(route.params.projectId))
const workspace = computed(() => datasetStore.workspace)
const workflow = computed(() => workspace.value?.workflow ?? null)
const taskFamily = computed(() => workflow.value?.taskFamily ?? workspace.value?.summary.taskFamily ?? 'bbox')
const latestTrainPoint = computed(() => {
  const metrics = runStore.latestTrain?.metrics ?? []
  return metrics[metrics.length - 1] ?? null
})

const annotationUnit = computed(() => (taskFamily.value === 'bbox' ? '框' : '实例'))

const summaryStats = computed(() => {
  const latestEvaluation = runStore.latestEvaluation
  const primaryMetric =
    taskFamily.value === 'bbox'
      ? { label: 'F1', value: latestEvaluation?.f1 }
      : { label: 'Dice', value: latestEvaluation?.dice ?? workspace.value?.latestEvaluationDice ?? null }

  return [
    { label: '工作流', value: workflow.value?.displayName ?? '-' },
    { label: '任务族', value: taskFamilyText(taskFamily.value) },
    { label: '待复核', value: String(workspace.value?.summary.reviewCount ?? 0) },
    { label: '激活版本', value: workspace.value?.activeModelTag ?? '-' },
    { label: primaryMetric.label, value: primaryMetric.value == null ? '--' : primaryMetric.value.toFixed(2) },
  ]
})

const workflowFacts = computed(() => [
  { label: 'workflow key', value: workflow.value?.key ?? '-' },
  { label: '运行配置', value: workspace.value?.runtimeProfile ?? '-' },
  { label: '最近微调', value: workspace.value?.latestFinetuneTag ?? '--' },
  { label: '标签', value: workspace.value?.labels.join('、') ?? '-' },
])

const evaluationFacts = computed(() => {
  const latest = runStore.latestEvaluation
  if (!latest) {
    return [
      { label: taskFamily.value === 'bbox' ? 'F1' : 'Dice', value: '--' },
      { label: taskFamily.value === 'bbox' ? '框 mIoU' : 'Mask mIoU', value: '--' },
      { label: '时延', value: '--' },
      { label: 'Fallback', value: '--' },
    ]
  }

  if (taskFamily.value === 'bbox') {
    return [
      { label: 'F1', value: latest.f1.toFixed(2) },
      { label: '框 mIoU', value: latest.miouBBox.toFixed(2) },
      { label: 'Precision', value: latest.precision.toFixed(2) },
      { label: 'Recall', value: latest.recall.toFixed(2) },
    ]
  }

  return [
    { label: 'Dice', value: latest.dice.toFixed(2) },
    { label: 'Mask mIoU', value: latest.miouMask.toFixed(2) },
    { label: 'F1', value: latest.f1.toFixed(2) },
    { label: 'Fallback', value: String(latest.fallbackImages) },
  ]
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

function trainStatusTone(status: string): 'success' | 'accent' | 'danger' | 'neutral' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'RUNNING' || status === 'QUEUED') return 'accent'
  if (status === 'FAILED') return 'danger'
  return 'neutral'
}
</script>

<template>
  <div class="overview-page">
    <TaskBanner v-if="workspace" :task="workspace.task" />

    <section class="overview-hero">
      <article v-for="item in summaryStats" :key="item.label" class="overview-stat">
        <span>{{ item.label }}</span>
        <strong class="mono">{{ item.value }}</strong>
      </article>
    </section>

    <div class="overview-grid">
      <SectionPanel>
        <template #header><strong>当前流程</strong></template>
        <div class="overview-fact-grid">
          <div v-for="item in workflowFacts" :key="item.label" class="overview-fact">
            <span>{{ item.label }}</span>
            <strong :class="{ mono: item.label !== '标签' }">{{ item.value }}</strong>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>最新评估</strong></template>
        <div class="overview-fact-grid">
          <div v-for="item in evaluationFacts" :key="item.label" class="overview-fact">
            <span>{{ item.label }}</span>
            <strong class="mono">{{ item.value }}</strong>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel class="overview-wide">
        <template #header><strong>待复核队列</strong></template>
        <div v-if="(workspace?.reviewQueue?.length ?? 0) === 0" class="overview-empty">当前没有待复核图片</div>
        <div v-else class="overview-list">
          <button
            v-for="item in workspace?.reviewQueue ?? []"
            :key="item.imageId"
            class="overview-row"
            @click="openAnnotate(item.imageId)"
          >
            <div class="overview-row-main">
              <strong>{{ item.filename }}</strong>
              <StatusChip :label="item.fallbackUsed ? '回退' : '正常'" :tone="item.fallbackUsed ? 'warning' : 'neutral'" />
            </div>
            <div class="overview-row-meta mono">
              <span>#{{ item.imageId }}</span>
              <span>质量={{ item.qualityScore?.toFixed(2) ?? '--' }}</span>
              <span>{{ annotationUnit }}={{ item.annotationCount }}</span>
            </div>
          </button>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>微调</strong></template>
        <div v-if="runStore.latestTrain" class="overview-stack">
          <div class="overview-line">
            <span>版本</span>
            <strong class="mono">{{ runStore.latestTrain.modelTag }}</strong>
          </div>
          <div class="overview-line">
            <span>状态</span>
            <StatusChip :label="taskStatusText(runStore.latestTrain.status)" :tone="trainStatusTone(runStore.latestTrain.status)" />
          </div>
          <div class="overview-line">
            <span>Loss</span>
            <strong class="mono">{{ latestTrainPoint?.loss?.toFixed(4) ?? '--' }}</strong>
          </div>
          <div class="overview-line">
            <span>轮次</span>
            <strong class="mono">{{ latestTrainPoint?.epoch ?? '--' }}/{{ latestTrainPoint?.epochTotal ?? '--' }}</strong>
          </div>
        </div>
        <div v-else class="overview-empty">当前没有微调记录</div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>评估记录</strong></template>
        <div v-if="runStore.latestEvaluation" class="overview-stack">
          <div class="overview-line">
            <span>版本</span>
            <strong class="mono">{{ runStore.latestEvaluation.modelTag }}</strong>
          </div>
          <div class="overview-line">
            <span>状态</span>
            <StatusChip :label="taskStatusText(runStore.latestEvaluation.status)" :tone="trainStatusTone(runStore.latestEvaluation.status)" />
          </div>
          <div class="overview-line">
            <span>创建时间</span>
            <strong class="mono">{{ runStore.latestEvaluation.createdAt }}</strong>
          </div>
          <div class="overview-line">
            <span>时延</span>
            <strong class="mono">{{ runStore.latestEvaluation.avgTotalMs }} ms/image</strong>
          </div>
        </div>
        <div v-else class="overview-empty">当前没有评估记录</div>
      </SectionPanel>
    </div>
  </div>
</template>

<style scoped>
.overview-page {
  display: grid;
  gap: 18px;
}

.overview-hero {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.overview-stat {
  display: grid;
  gap: 10px;
  padding: 16px 18px;
  border: 1px solid rgba(106, 126, 152, 0.14);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 18px 42px rgba(20, 35, 58, 0.05);
}

.overview-stat span {
  color: var(--text-muted);
  font-size: 13px;
}

.overview-stat strong {
  font-size: 22px;
  color: var(--text-strong);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.overview-wide {
  grid-column: 1 / -1;
}

.overview-fact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.overview-fact {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid rgba(106, 126, 152, 0.12);
  border-radius: 18px;
  background: var(--panel-soft);
}

.overview-fact span,
.overview-row-meta,
.overview-line span {
  color: var(--text-muted);
  font-size: 13px;
}

.overview-fact strong,
.overview-line strong {
  color: var(--text-strong);
}

.overview-list,
.overview-stack {
  display: grid;
  gap: 10px;
}

.overview-row {
  display: grid;
  gap: 10px;
  padding: 16px;
  border-radius: 20px;
  background: var(--panel-soft);
  text-align: left;
}

.overview-row-main,
.overview-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.overview-row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.overview-line {
  padding: 12px 0;
  border-bottom: 1px solid rgba(106, 126, 152, 0.12);
}

.overview-line:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.overview-empty {
  color: var(--text-muted);
}

@media (max-width: 1080px) {
  .overview-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-grid,
  .overview-fact-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .overview-hero {
    grid-template-columns: 1fr;
  }
}
</style>
