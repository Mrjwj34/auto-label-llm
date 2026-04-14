<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import LabelListEditor from '../../components/LabelListEditor.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import { useProjectStore } from '../../stores/projectStore'
import { useRunStore } from '../../stores/runStore'
import { taskFamilyText } from '../../utils/uiText'

const route = useRoute()
const projectStore = useProjectStore()
const runStore = useRunStore()
const projectId = computed(() => Number(route.params.projectId))

const workflowKey = ref('generic_instance_segmentation')
const labels = ref<string[]>([])
const activeModelTag = ref('base')
const feedbackMessage = ref('')

const projectWorkflowOptions = computed(() => {
  const taskType = projectStore.currentProject?.taskType
  const workflows = projectStore.settings?._meta.availableWorkflows ?? projectStore.workflows
  if (!taskType) return workflows
  return workflows.filter((workflow) => workflow.taskType === taskType)
})

const availableModelTags = computed(() => {
  const values = ['base', activeModelTag.value]
  for (const job of runStore.trainJobs) {
    if (job.status === 'SUCCESS') {
      values.push(job.modelTag)
    }
  }
  return values.filter((value, index) => values.indexOf(value) === index)
})

function applyProjectSettings() {
  workflowKey.value = projectStore.settings?.workflowKey ?? 'generic_instance_segmentation'
  labels.value = [...(projectStore.settings?.labels ?? [])]
  activeModelTag.value = projectStore.settings?.activeModelTag ?? 'base'
}

async function hydrate(nextProjectId: number) {
  await Promise.all([projectStore.loadProject(nextProjectId), runStore.load(nextProjectId)])
  applyProjectSettings()
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
  () => {
    applyProjectSettings()
  },
)

async function saveProjectSettings() {
  feedbackMessage.value = ''
  await projectStore.saveSettings(projectId.value, {
    workflowKey: workflowKey.value,
    labels: [...labels.value],
    activeModelTag: activeModelTag.value,
  })
  await Promise.all([projectStore.loadProject(projectId.value), runStore.load(projectId.value)])
  feedbackMessage.value = '已保存项目设置。'
}
</script>

<template>
  <div class="settings-page">
    <SectionPanel>
      <template #header><strong>项目设置</strong></template>
      <template #actions>
        <button class="primary" :disabled="projectStore.saving" @click="saveProjectSettings">保存项目设置</button>
      </template>

      <div class="project-summary">
        <div class="project-summary-item">
          <span>当前工作流</span>
          <strong>{{ projectStore.settings?.workflow.displayName ?? '-' }}</strong>
        </div>
        <div class="project-summary-item">
          <span>任务族</span>
          <strong>{{ taskFamilyText(projectStore.settings?.taskFamily ?? '-') }}</strong>
        </div>
        <div class="project-summary-item">
          <span>激活版本</span>
          <strong class="mono">{{ projectStore.settings?.activeModelTag ?? 'base' }}</strong>
        </div>
      </div>

      <div class="project-form">
        <label class="project-form-row">
          <span>工作流</span>
          <select v-model="workflowKey">
            <option v-for="workflow in projectWorkflowOptions" :key="workflow.key" :value="workflow.key">
              {{ workflow.displayName }}
            </option>
          </select>
        </label>

        <label class="project-form-row">
          <span>激活版本</span>
          <select v-model="activeModelTag">
            <option v-for="modelTag in availableModelTags" :key="modelTag" :value="modelTag">
              {{ modelTag }}
            </option>
          </select>
        </label>

        <label class="project-form-row project-form-row-wide">
          <span>标签</span>
          <LabelListEditor v-model="labels" placeholder="输入标签后按回车" />
        </label>
      </div>

      <div v-if="feedbackMessage || projectStore.settingsChange" class="settings-change">
        <strong>{{ feedbackMessage || '已保存项目设置。' }}</strong>
      </div>
    </SectionPanel>
  </div>
</template>

<style scoped>
.settings-page {
  display: grid;
  gap: 16px;
}

.project-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.project-summary-item {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px 14px;
}

.project-summary-item span,
.project-form-row > span {
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
}

.project-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.project-form-row {
  display: grid;
  gap: 8px;
}

.project-form-row-wide {
  grid-column: 1 / -1;
}

.settings-change {
  margin-top: 14px;
  border-top: 1px solid var(--line);
  padding-top: 12px;
  color: var(--accent);
}

@media (max-width: 860px) {
  .project-summary,
  .project-form {
    grid-template-columns: 1fr;
  }
}
</style>
