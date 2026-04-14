<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { ProjectSettingsPayload, SystemSettingsPayload } from '../../backend/types'
import LabelListEditor from '../../components/LabelListEditor.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import { useProjectStore } from '../../stores/projectStore'
import { useSystemRuntimeStore } from '../../stores/systemRuntimeStore'
import { annotationBackendText, splitText, taskFamilyText, taskTypeText } from '../../utils/uiText'

const route = useRoute()
const projectStore = useProjectStore()
const systemStore = useSystemRuntimeStore()
const projectId = computed(() => Number(route.params.projectId))

const workflowKey = ref('generic_instance_segmentation')
const labels = ref<string[]>([])

const llmBaseModel = ref('qwen3-vl-2b')
const llmAutoOrderText = ref('2b, 4b, 8b')
const llmMaxTokens = ref(2048)
const samCheckpoint = ref('sam2')
const samDevice = ref<SystemSettingsPayload['sam']['device']>('cpu')
const samMultimaskOutput = ref(false)
const postprocessEnableClose = ref(false)
const postprocessCloseKernel = ref(5)
const postprocessEnableDpSimplify = ref(false)
const postprocessEpsilonRatio = ref(0.002)
const postprocessMinAreaRatio = ref(0.0005)
const qualityEnable = ref(true)
const qualityThresholdReview = ref(0.6)
const qualityThresholdOk = ref(0.8)
const qualityUseLlmConfidence = ref(true)
const qualityUseSamScore = ref(true)
const qualityEnableConsistencyCheck = ref(false)
const evaluationSplit = ref<SystemSettingsPayload['evaluation']['split']>('val')
const evaluationIouThreshold = ref(0.5)
const evaluationMaxSamples = ref<number | null>(120)

const projectWorkflowOptions = computed(() => {
  const taskType = projectStore.currentProject?.taskType
  const workflows = projectStore.settings?._meta.availableWorkflows ?? projectStore.workflows
  if (!taskType) return workflows
  return workflows.filter((workflow) => workflow.taskType === taskType)
})

const currentWorkflow = computed(() => projectStore.settings?.workflow ?? null)
const samEnabledForProject = computed(() => currentWorkflow.value?.capabilities.includes('sam_refine') ?? false)

const currentBaseModel = computed(() => systemStore.systemSettings?.llm.baseModel ?? llmBaseModel.value)
const currentAnnotationBackend = computed(() => annotationBackendText(systemStore.systemConfig?.runtime.annotationBackend ?? '-'))
const currentTaskType = computed(() => taskTypeText(projectStore.currentProject?.taskType ?? '-'))
const currentTaskFamily = computed(() => taskFamilyText(projectStore.settings?.taskFamily ?? '-'))

const modelTagHint = computed(() => {
  const modelTag = projectStore.settings?.activeModelTag ?? 'base'
  if (modelTag === 'base') {
    return `base 表示当前走基础模型通道，不是具体模型名；当前基础模型是 ${currentBaseModel.value}。`
  }
  return `当前激活的是 ${modelTag} 这条模型标签，底层基础模型仍然是 ${currentBaseModel.value}。`
})

const samScopeHint = computed(() =>
  samEnabledForProject.value
    ? 'SAM 是全局分割默认值，只影响新的分割任务；不会只对当前项目单独生效。'
    : '当前项目是检测任务，不使用 SAM refine，因此这里不展示可编辑的 SAM 配置。',
)

const systemSaveMessage = computed(() => {
  if (!systemStore.settingsChange) return ''
  return systemStore.settingsChange.reloadRequired
    ? '已保存全局默认值。基础模型和 SAM 类变更需要重新加载相关服务后才会完整生效。'
    : '已保存全局默认值。新的任务会使用最新配置。'
})

const projectSaveMessage = computed(() => {
  if (!projectStore.settingsChange) return ''
  return '已保存项目设置。新的任务会使用最新的工作流与标签。'
})

const llmBaseModelOptions = computed(() => mergeStringOptions(llmBaseModel.value, ['qwen3-vl-2b', 'qwen3-vl-4b', 'qwen3-vl-8b']))
const llmAutoOrderOptions = computed(() => {
  const currentValue = formatAutoOrder(parseAutoOrder(llmAutoOrderText.value))
  const presets = [
    { value: '2b, 4b, 8b', label: '低成本优先' },
    { value: '4b, 8b, 2b', label: '均衡' },
    { value: '8b, 4b, 2b', label: '效果优先' },
  ]
  if (!currentValue || presets.some((item) => item.value === currentValue)) {
    return presets
  }
  return [{ value: currentValue, label: `当前顺序（${currentValue}）` }, ...presets]
})
const llmMaxTokenOptions = computed(() => mergeNumberOptions(llmMaxTokens.value, [1024, 2048, 3072, 4096]))
const samCheckpointOptions = computed(() => mergeStringOptions(samCheckpoint.value, ['sam2', 'sam2.1']))
const postprocessKernelOptions = computed(() => mergeNumberOptions(postprocessCloseKernel.value, [3, 5, 7, 9]))
const postprocessEpsilonOptions = computed(() => mergeNumberOptions(postprocessEpsilonRatio.value, [0.001, 0.002, 0.004, 0.006]))
const postprocessMinAreaOptions = computed(() => mergeNumberOptions(postprocessMinAreaRatio.value, [0.0001, 0.0003, 0.0005, 0.001]))
const qualityReviewOptions = computed(() => mergeNumberOptions(qualityThresholdReview.value, [0.5, 0.55, 0.6, 0.65, 0.7]))
const qualityOkOptions = computed(() => mergeNumberOptions(qualityThresholdOk.value, [0.75, 0.8, 0.85, 0.9]))
const evaluationIouOptions = computed(() => mergeNumberOptions(evaluationIouThreshold.value, [0.4, 0.5, 0.6, 0.7]))
const evaluationMaxSampleOptions = computed(() => mergeNullableNumberOptions(evaluationMaxSamples.value, [null, 50, 120, 200, 500]))

function mergeStringOptions(current: string, defaults: string[]): string[] {
  const values = [current, ...defaults].filter((value) => value.trim().length > 0)
  return values.filter((value, index) => values.indexOf(value) === index)
}

function mergeNumberOptions(current: number, defaults: number[]): number[] {
  const values = [current, ...defaults]
  return values.filter((value, index) => values.indexOf(value) === index)
}

function mergeNullableNumberOptions(current: number | null, defaults: Array<number | null>): Array<number | null> {
  const values = [current, ...defaults]
  return values.filter((value, index) => values.findIndex((candidate) => candidate === value) === index)
}

function formatAutoOrder(order: string[]): string {
  return order.join(', ')
}

function parseAutoOrder(text: string): string[] {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function applyProjectSettings(settings: ProjectSettingsPayload | null) {
  workflowKey.value = settings?.workflowKey ?? 'generic_instance_segmentation'
  labels.value = [...(settings?.labels ?? [])]
}

function applySystemSettings(settings: SystemSettingsPayload | null) {
  if (!settings) return
  llmBaseModel.value = settings.llm.baseModel
  llmAutoOrderText.value = formatAutoOrder(settings.llm.autoOrder)
  llmMaxTokens.value = settings.llm.maxTokens
  samCheckpoint.value = settings.sam.checkpoint
  samDevice.value = settings.sam.device
  samMultimaskOutput.value = settings.sam.multimaskOutput
  postprocessEnableClose.value = settings.postprocess.enableClose
  postprocessCloseKernel.value = settings.postprocess.closeKernel
  postprocessEnableDpSimplify.value = settings.postprocess.enableDpSimplify
  postprocessEpsilonRatio.value = settings.postprocess.epsilonRatio
  postprocessMinAreaRatio.value = settings.postprocess.minAreaRatio
  qualityEnable.value = settings.quality.enable
  qualityThresholdReview.value = settings.quality.thresholdReview
  qualityThresholdOk.value = settings.quality.thresholdOk
  qualityUseLlmConfidence.value = settings.quality.useLlmConfidence
  qualityUseSamScore.value = settings.quality.useSamScore
  qualityEnableConsistencyCheck.value = settings.quality.enableConsistencyCheck
  evaluationSplit.value = settings.evaluation.split
  evaluationIouThreshold.value = settings.evaluation.iouThreshold
  evaluationMaxSamples.value = settings.evaluation.maxSamples
}

async function hydrate(nextProjectId: number) {
  await Promise.all([projectStore.loadProject(nextProjectId), systemStore.loadRuntime()])
  applyProjectSettings(projectStore.settings)
  applySystemSettings(systemStore.systemSettings)
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

watch(
  () => projectStore.settings,
  (settings) => {
    applyProjectSettings(settings)
  },
)

watch(
  () => systemStore.systemSettings,
  (settings) => {
    applySystemSettings(settings)
  },
)

async function saveProjectSettings() {
  await projectStore.saveSettings(projectId.value, {
    workflowKey: workflowKey.value,
    labels: [...labels.value],
  })
}

async function saveSystemSettings() {
  const patch: Partial<SystemSettingsPayload> = {
    llm: {
      baseModel: llmBaseModel.value.trim(),
      autoOrder: parseAutoOrder(llmAutoOrderText.value),
      maxTokens: llmMaxTokens.value,
    },
    postprocess: {
      enableClose: postprocessEnableClose.value,
      closeKernel: postprocessCloseKernel.value,
      enableDpSimplify: postprocessEnableDpSimplify.value,
      epsilonRatio: postprocessEpsilonRatio.value,
      minAreaRatio: postprocessMinAreaRatio.value,
    },
    quality: {
      enable: qualityEnable.value,
      thresholdReview: qualityThresholdReview.value,
      thresholdOk: qualityThresholdOk.value,
      useLlmConfidence: qualityUseLlmConfidence.value,
      useSamScore: qualityUseSamScore.value,
      enableConsistencyCheck: qualityEnableConsistencyCheck.value,
    },
    evaluation: {
      split: evaluationSplit.value,
      iouThreshold: evaluationIouThreshold.value,
      maxSamples: evaluationMaxSamples.value,
    },
  }

  if (samEnabledForProject.value) {
    patch.sam = {
      checkpoint: samCheckpoint.value.trim(),
      device: samDevice.value,
      multimaskOutput: samMultimaskOutput.value,
    }
  }

  await systemStore.saveSystemSettings(patch)
  await projectStore.loadProject(projectId.value)
}
</script>

<template>
  <div class="settings-page">
    <SectionPanel>
      <template #header><strong>全局运行默认值</strong></template>
      <template #actions>
        <button class="primary" :disabled="systemStore.saving" @click="saveSystemSettings">保存全局默认值</button>
      </template>

      <div class="settings-intro">
        <p>启动脚本会先写入一组默认值；前端现在只展示服务启动后已经生效的全局默认值，不再显示脚本配置档名。</p>
      </div>

      <div class="settings-card-grid">
        <div class="settings-card">
          <span>标注后端</span>
          <strong class="mono">{{ currentAnnotationBackend }}</strong>
        </div>
        <div class="settings-card">
          <span>当前基础模型</span>
          <strong class="mono">{{ currentBaseModel }}</strong>
        </div>
        <div class="settings-card">
          <span>当前任务类型</span>
          <strong>{{ currentTaskType }}</strong>
        </div>
        <div class="settings-card">
          <span>SAM 默认值</span>
          <strong class="mono">{{ samEnabledForProject ? samCheckpoint : '当前任务不使用' }}</strong>
        </div>
      </div>

      <div class="settings-sections">
        <section class="settings-block">
          <div class="settings-block-head">
            <h3>模型默认值</h3>
            <p>基础模型和路由顺序只提供预设选项，避免自由输入带来的误操作。</p>
          </div>
          <div class="settings-fields">
            <label class="settings-field">
              <span>基础模型</span>
              <select v-model="llmBaseModel">
                <option v-for="option in llmBaseModelOptions" :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>自动路由顺序</span>
              <select v-model="llmAutoOrderText">
                <option v-for="option in llmAutoOrderOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>最大输出 Tokens</span>
              <select v-model.number="llmMaxTokens">
                <option v-for="option in llmMaxTokenOptions" :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
            </label>
          </div>
        </section>

        <section v-if="samEnabledForProject" class="settings-block">
          <div class="settings-block-head">
            <h3>SAM 默认值</h3>
            <p>{{ samScopeHint }}</p>
          </div>
          <div class="settings-fields">
            <label class="settings-field">
              <span>Checkpoint</span>
              <select v-model="samCheckpoint">
                <option v-for="option in samCheckpointOptions" :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>设备</span>
              <select v-model="samDevice">
                <option value="cpu">cpu</option>
                <option value="cuda">cuda</option>
              </select>
            </label>
            <label class="settings-toggle">
              <input v-model="samMultimaskOutput" type="checkbox" />
              <span>多掩码输出</span>
            </label>
          </div>
        </section>

        <section v-else class="settings-block settings-block-note">
          <div class="settings-block-head">
            <h3>SAM</h3>
            <p>{{ samScopeHint }}</p>
          </div>
        </section>

        <section class="settings-block">
          <div class="settings-block-head">
            <h3>后处理默认值</h3>
            <p>保留常用预设，减少手动输入阈值的风险。</p>
          </div>
          <div class="settings-fields">
            <label class="settings-toggle">
              <input v-model="postprocessEnableClose" type="checkbox" />
              <span>闭运算</span>
            </label>
            <label class="settings-field">
              <span>闭运算核</span>
              <select v-model.number="postprocessCloseKernel">
                <option v-for="option in postprocessKernelOptions" :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
            </label>
            <label class="settings-toggle">
              <input v-model="postprocessEnableDpSimplify" type="checkbox" />
              <span>DP 简化</span>
            </label>
            <label class="settings-field">
              <span>简化比例</span>
              <select v-model.number="postprocessEpsilonRatio">
                <option v-for="option in postprocessEpsilonOptions" :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>最小面积比例</span>
              <select v-model.number="postprocessMinAreaRatio">
                <option v-for="option in postprocessMinAreaOptions" :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
            </label>
          </div>
        </section>

        <section class="settings-block">
          <div class="settings-block-head">
            <h3>质量门控</h3>
            <p>质量阈值改成下拉选择，避免误填无效小数。</p>
          </div>
          <div class="settings-fields">
            <label class="settings-toggle">
              <input v-model="qualityEnable" type="checkbox" />
              <span>启用质量打分</span>
            </label>
            <label class="settings-field">
              <span>待复核阈值</span>
              <select v-model.number="qualityThresholdReview">
                <option v-for="option in qualityReviewOptions" :key="option" :value="option">
                  {{ option.toFixed(2) }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>通过阈值</span>
              <select v-model.number="qualityThresholdOk">
                <option v-for="option in qualityOkOptions" :key="option" :value="option">
                  {{ option.toFixed(2) }}
                </option>
              </select>
            </label>
            <label class="settings-toggle">
              <input v-model="qualityUseLlmConfidence" type="checkbox" />
              <span>使用 LLM 置信度</span>
            </label>
            <label class="settings-toggle">
              <input v-model="qualityUseSamScore" type="checkbox" />
              <span>使用 SAM 分数</span>
            </label>
            <label class="settings-toggle">
              <input v-model="qualityEnableConsistencyCheck" type="checkbox" />
              <span>一致性检查</span>
            </label>
          </div>
        </section>

        <section class="settings-block">
          <div class="settings-block-head">
            <h3>评估默认值</h3>
            <p>这里只保留常见的评估预设，不再让用户直接输入自由值。</p>
          </div>
          <div class="settings-fields">
            <label class="settings-field">
              <span>默认数据划分</span>
              <select v-model="evaluationSplit">
                <option value="train">{{ splitText('train') }}</option>
                <option value="val">{{ splitText('val') }}</option>
                <option value="test">{{ splitText('test') }}</option>
              </select>
            </label>
            <label class="settings-field">
              <span>IoU 阈值</span>
              <select v-model.number="evaluationIouThreshold">
                <option v-for="option in evaluationIouOptions" :key="option" :value="option">
                  {{ option.toFixed(2) }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>最大样本数</span>
              <select v-model="evaluationMaxSamples">
                <option v-for="option in evaluationMaxSampleOptions" :key="option ?? 'all'" :value="option">
                  {{ option == null ? '不限' : option }}
                </option>
              </select>
            </label>
          </div>
        </section>
      </div>

      <div v-if="systemStore.settingsChange" class="settings-change">
        <strong>{{ systemSaveMessage }}</strong>
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>项目设置</strong></template>
      <template #actions>
        <button class="primary" :disabled="projectStore.saving" @click="saveProjectSettings">保存项目设置</button>
      </template>

      <div class="settings-intro">
        <p>项目级现在只保留工作流和标签。模型、SAM、评估等设置统一按上面的全局默认值执行。</p>
      </div>

      <div class="settings-card-grid">
        <div class="settings-card">
          <span>当前模型标签</span>
          <strong class="mono">{{ projectStore.settings?.activeModelTag ?? '-' }}</strong>
        </div>
        <div class="settings-card">
          <span>当前基础模型</span>
          <strong class="mono">{{ currentBaseModel }}</strong>
        </div>
        <div class="settings-card">
          <span>任务类型</span>
          <strong>{{ currentTaskType }}</strong>
        </div>
        <div class="settings-card">
          <span>任务族</span>
          <strong>{{ currentTaskFamily }}</strong>
        </div>
      </div>

      <div class="settings-inline-note mono">
        {{ modelTagHint }}
      </div>

      <div class="settings-sections settings-sections-project">
        <section class="settings-block">
          <div class="settings-block-head">
            <h3>项目级可编辑项</h3>
            <p>这里只保留真正会写入项目的字段：工作流和标签。</p>
          </div>
          <div class="settings-fields">
            <label class="settings-field">
              <span>工作流</span>
              <select v-model="workflowKey">
                <option v-for="workflow in projectWorkflowOptions" :key="workflow.key" :value="workflow.key">
                  {{ workflow.displayName }}
                </option>
              </select>
            </label>
            <label class="settings-field">
              <span>标签</span>
              <LabelListEditor
                v-model="labels"
                placeholder="一次输入一个标签，例如：裂缝"
                helper="标签按项维护；保存时会整理成标签列表提交。"
              />
            </label>
          </div>
        </section>

        <section class="settings-block">
          <div class="settings-block-head">
            <h3>当前工作流能力</h3>
            <p>工作流决定当前项目是否支持自动标注、SAM refine 和点修正。</p>
          </div>
          <div class="settings-summary-list">
            <div class="settings-summary-row">
              <span>工作流</span>
              <strong>{{ currentWorkflow?.displayName ?? '-' }}</strong>
            </div>
            <div class="settings-summary-row">
              <span>自动标注</span>
              <strong>{{ currentWorkflow?.supportsAutoAnnotation ? '开启' : '关闭' }}</strong>
            </div>
            <div class="settings-summary-row">
              <span>手工框编辑</span>
              <strong>{{ currentWorkflow?.supportsManualBBox ? '开启' : '关闭' }}</strong>
            </div>
            <div class="settings-summary-row">
              <span>点修正</span>
              <strong>{{ currentWorkflow?.supportsPointRefine ? '开启' : '关闭' }}</strong>
            </div>
            <div class="settings-summary-row">
              <span>SAM refine</span>
              <strong>{{ samEnabledForProject ? '开启' : '关闭' }}</strong>
            </div>
          </div>
        </section>
      </div>

      <div v-if="projectStore.settingsChange" class="settings-change">
        <strong>{{ projectSaveMessage }}</strong>
      </div>
    </SectionPanel>
  </div>
</template>

<style scoped>
.settings-page {
  display: grid;
  gap: 16px;
}

.settings-intro {
  color: var(--text-muted);
  font-size: 14px;
}

.settings-intro p {
  margin: 0;
}

.settings-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.settings-card {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px 16px;
}

.settings-card span {
  color: var(--text-muted);
  font-size: 13px;
}

.settings-card strong {
  color: var(--text-strong);
  font-size: 18px;
}

.settings-inline-note {
  margin-top: 14px;
  color: var(--text-muted);
  font-size: 13px;
}

.settings-sections {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.settings-sections-project {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}

.settings-block {
  display: grid;
  gap: 14px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 16px;
}

.settings-block-head {
  display: grid;
  gap: 6px;
}

.settings-block h3 {
  margin: 0;
  font-size: 16px;
}

.settings-block p {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.settings-block-note {
  align-content: start;
}

.settings-fields {
  display: grid;
  gap: 12px;
}

.settings-field {
  display: grid;
  gap: 8px;
}

.settings-field span {
  color: var(--text-muted);
  font-size: 13px;
}

.settings-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-strong);
}

.settings-summary-list {
  display: grid;
  gap: 10px;
}

.settings-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--line);
  background: var(--panel);
  padding: 10px 12px;
}

.settings-summary-row span {
  color: var(--text-muted);
  font-size: 13px;
}

.settings-summary-row strong {
  color: var(--text-strong);
}

.settings-change {
  margin-top: 16px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px 16px;
  color: var(--text-strong);
}

@media (max-width: 1200px) {
  .settings-card-grid,
  .settings-sections,
  .settings-sections-project {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .settings-card-grid,
  .settings-sections,
  .settings-sections-project {
    grid-template-columns: 1fr;
  }

  .settings-summary-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
