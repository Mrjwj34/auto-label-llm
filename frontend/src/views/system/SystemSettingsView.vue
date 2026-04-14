<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { SystemSettingsPayload } from '../../backend/types'
import SectionPanel from '../../components/SectionPanel.vue'
import { useSystemRuntimeStore } from '../../stores/systemRuntimeStore'
import { annotationBackendText, splitText } from '../../utils/uiText'

const systemStore = useSystemRuntimeStore()

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

const summaryRows = computed(() => [
  { label: '当前配置档', value: systemStore.systemConfig?.activeProfile ?? '-' },
  { label: '标注后端', value: annotationBackendText(systemStore.systemConfig?.runtime.annotationBackend ?? '-') },
  { label: '基础模型', value: systemStore.systemSettings?.llm.baseModel ?? '-' },
  { label: '配置文件', value: systemStore.systemSettings?._meta.storagePath ?? '-' },
])

const llmBaseModelOptions = computed(() => mergeStringOptions(llmBaseModel.value, ['qwen3-vl-2b', 'qwen3-vl-4b', 'qwen3-vl-8b']))
const llmAutoOrderOptions = computed(() => {
  const currentValue = formatAutoOrder(parseAutoOrder(llmAutoOrderText.value))
  const presets = [
    { value: '2b, 4b, 8b', label: '2b, 4b, 8b' },
    { value: '4b, 8b, 2b', label: '4b, 8b, 2b' },
    { value: '8b, 4b, 2b', label: '8b, 4b, 2b' },
  ]
  if (!currentValue || presets.some((item) => item.value === currentValue)) {
    return presets
  }
  return [{ value: currentValue, label: currentValue }, ...presets]
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

const saveMessage = computed(() => {
  if (!systemStore.settingsChange) return ''
  return systemStore.settingsChange.reloadRequired
    ? '已保存全局设置。部分变更需要重新加载服务。'
    : '已保存全局设置。'
})

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

onMounted(() => {
  void systemStore.loadRuntime()
})

watch(
  () => systemStore.systemSettings,
  (settings) => {
    applySystemSettings(settings)
  },
  { immediate: true },
)

async function saveSystemSettings() {
  const patch: Partial<SystemSettingsPayload> = {
    llm: {
      baseModel: llmBaseModel.value.trim(),
      autoOrder: parseAutoOrder(llmAutoOrderText.value),
      maxTokens: llmMaxTokens.value,
    },
    sam: {
      checkpoint: samCheckpoint.value.trim(),
      device: samDevice.value,
      multimaskOutput: samMultimaskOutput.value,
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
  await systemStore.saveSystemSettings(patch)
}
</script>

<template>
  <div class="page-frame">
    <header class="page-header">
      <div>
        <h1 class="page-title">全局设置</h1>
        <div class="page-meta mono">active-profile={{ systemStore.systemConfig?.activeProfile ?? '-' }}</div>
      </div>
      <div>
        <button class="primary" :disabled="systemStore.saving" @click="saveSystemSettings">保存全局设置</button>
      </div>
    </header>

    <SectionPanel>
      <template #header><strong>当前状态</strong></template>
      <div class="system-summary">
        <div v-for="row in summaryRows" :key="row.label" class="system-summary-item">
          <span>{{ row.label }}</span>
          <strong class="mono">{{ row.value }}</strong>
        </div>
      </div>
    </SectionPanel>

    <SectionPanel>
      <template #header><strong>配置档</strong></template>
      <div class="profile-list">
        <button
          v-for="profile in systemStore.systemConfig?.profiles ?? []"
          :key="profile.name"
          class="profile-row"
          :class="{ active: systemStore.systemConfig?.activeProfile === profile.name }"
          @click="systemStore.activateProfile(profile.name)"
        >
          <strong>{{ profile.name }}</strong>
          <div class="profile-meta mono">
            <span>{{ annotationBackendText(profile.annotationBackend) }}</span>
            <span>{{ profile.modelName }}</span>
          </div>
        </button>
      </div>
    </SectionPanel>

    <div class="system-grid">
      <SectionPanel>
        <template #header><strong>模型</strong></template>
        <div class="settings-fields">
          <label class="settings-field">
            <span>基础模型</span>
            <select v-model="llmBaseModel">
              <option v-for="option in llmBaseModelOptions" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>自动路由顺序</span>
            <select v-model="llmAutoOrderText">
              <option v-for="option in llmAutoOrderOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>最大输出 Tokens</span>
            <select v-model.number="llmMaxTokens">
              <option v-for="option in llmMaxTokenOptions" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>SAM</strong></template>
        <div class="settings-fields">
          <label class="settings-field">
            <span>Checkpoint</span>
            <select v-model="samCheckpoint">
              <option v-for="option in samCheckpointOptions" :key="option" :value="option">{{ option }}</option>
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
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>后处理</strong></template>
        <div class="settings-fields">
          <label class="settings-toggle">
            <input v-model="postprocessEnableClose" type="checkbox" />
            <span>闭运算</span>
          </label>
          <label class="settings-field">
            <span>闭运算核</span>
            <select v-model.number="postprocessCloseKernel">
              <option v-for="option in postprocessKernelOptions" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
          <label class="settings-toggle">
            <input v-model="postprocessEnableDpSimplify" type="checkbox" />
            <span>DP 简化</span>
          </label>
          <label class="settings-field">
            <span>简化比例</span>
            <select v-model.number="postprocessEpsilonRatio">
              <option v-for="option in postprocessEpsilonOptions" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>最小面积比例</span>
            <select v-model.number="postprocessMinAreaRatio">
              <option v-for="option in postprocessMinAreaOptions" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>质量门控</strong></template>
        <div class="settings-fields">
          <label class="settings-toggle">
            <input v-model="qualityEnable" type="checkbox" />
            <span>启用质量打分</span>
          </label>
          <label class="settings-field">
            <span>待复核阈值</span>
            <select v-model.number="qualityThresholdReview">
              <option v-for="option in qualityReviewOptions" :key="option" :value="option">{{ option.toFixed(2) }}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>通过阈值</span>
            <select v-model.number="qualityThresholdOk">
              <option v-for="option in qualityOkOptions" :key="option" :value="option">{{ option.toFixed(2) }}</option>
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
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>评估默认值</strong></template>
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
              <option v-for="option in evaluationIouOptions" :key="option" :value="option">{{ option.toFixed(2) }}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>最大样本数</span>
            <select v-model="evaluationMaxSamples">
              <option v-for="option in evaluationMaxSampleOptions" :key="option ?? 'all'" :value="option">{{ option == null ? '不限' : option }}</option>
            </select>
          </label>
        </div>
      </SectionPanel>
    </div>

    <SectionPanel v-if="saveMessage">
      <template #header><strong>保存结果</strong></template>
      <div class="save-message mono">{{ saveMessage }}</div>
    </SectionPanel>
  </div>
</template>

<style scoped>
.system-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.system-summary-item {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px 14px;
}

.system-summary-item span,
.settings-field span,
.profile-meta,
.save-message {
  color: var(--text-muted);
  font-size: 12px;
}

.profile-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.profile-row {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px;
  text-align: left;
}

.profile-row.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.profile-meta {
  display: grid;
  gap: 4px;
}

.system-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.settings-fields {
  display: grid;
  gap: 12px;
}

.settings-field,
.settings-toggle {
  display: grid;
  gap: 8px;
}

.settings-toggle {
  grid-template-columns: auto 1fr;
  align-items: center;
}

@media (max-width: 1080px) {
  .system-summary,
  .profile-list,
  .system-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .system-summary,
  .profile-list,
  .system-grid {
    grid-template-columns: 1fr;
  }
}
</style>
