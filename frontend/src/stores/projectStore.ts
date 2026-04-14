import { defineStore } from 'pinia'
import { backendClient } from '../backend/client'
import type { ProjectMetaPayload, ProjectSettingsPayload, ProjectSummary, SettingsChange, TaskType, WorkflowDefinition } from '../backend/types'

type CreateDraft = {
  name: string
  taskType: TaskType
  workflowKey: string
  labels: string[]
}

function defaultWorkflowKeyForTaskType(meta: Pick<ProjectMetaPayload, 'defaultWorkflows' | 'workflows'>, taskType: TaskType): string {
  return meta.defaultWorkflows[taskType] ?? meta.workflows.find((workflow) => workflow.taskType === taskType)?.key ?? ''
}

export const useProjectStore = defineStore('project', {
  state: () => ({
    loading: false,
    saving: false,
    projects: [] as ProjectSummary[],
    taskTypes: ['detection', 'segmentation'] as TaskType[],
    defaultWorkflows: {
      detection: 'generic_detection',
      segmentation: 'generic_instance_segmentation',
    } as Record<TaskType, string>,
    workflows: [] as WorkflowDefinition[],
    currentProject: null as ProjectSummary | null,
    settings: null as ProjectSettingsPayload | null,
    settingsChange: null as SettingsChange | null,
    createDrawerOpen: false,
    search: '',
    workflowFilter: 'all',
    createDraft: {
      name: '',
      taskType: 'segmentation',
      workflowKey: 'generic_instance_segmentation',
      labels: [],
    } as CreateDraft,
  }),
  getters: {
    filteredProjects(state) {
      const query = state.search.trim().toLowerCase()
      return state.projects.filter((project) => {
        const matchesWorkflow = state.workflowFilter === 'all' || project.workflowKey === state.workflowFilter
        const matchesQuery =
          query.length === 0 ||
          project.name.toLowerCase().includes(query) ||
          project.taskType.toLowerCase().includes(query) ||
          project.workflowKey.toLowerCase().includes(query)
        return matchesWorkflow && matchesQuery
      })
    },
    selectedWorkflow(state) {
      return state.workflows.find((workflow) => workflow.key === state.createDraft.workflowKey) ?? null
    },
    availableCreateWorkflows(state) {
      return state.workflows.filter((workflow) => workflow.taskType === state.createDraft.taskType)
    },
  },
  actions: {
    async loadProjects() {
      this.loading = true
      try {
        const [projects, meta] = await Promise.all([backendClient.listProjects(), backendClient.getProjectMeta()])
        this.projects = projects
        this.taskTypes = [...meta.taskTypes]
        this.defaultWorkflows = { ...meta.defaultWorkflows }
        this.workflows = meta.workflows
      } finally {
        this.loading = false
      }
    },
    async loadProject(projectId: number) {
      if (!this.projects.length) {
        await this.loadProjects()
      }
      this.currentProject = this.projects.find((project) => project.id === projectId) ?? null
      this.settings = await backendClient.getProjectSettings(projectId)
      this.settingsChange = null
    },
    openCreateDrawer(workflowKey?: string) {
      const workflow = workflowKey ? this.workflows.find((item) => item.key === workflowKey) ?? null : null
      const taskType = workflow?.taskType ?? this.taskTypes[0] ?? 'segmentation'
      this.createDrawerOpen = true
      this.createDraft = {
        name: '',
        taskType,
        workflowKey: workflow?.key ?? defaultWorkflowKeyForTaskType(this, taskType) ?? 'generic_instance_segmentation',
        labels: [],
      }
    },
    closeCreateDrawer() {
      this.createDrawerOpen = false
    },
    setCreateTaskType(taskType: TaskType) {
      this.createDraft.taskType = taskType
      const workflowStillValid = this.workflows.some(
        (workflow) => workflow.key === this.createDraft.workflowKey && workflow.taskType === taskType,
      )
      if (!workflowStillValid) {
        this.createDraft.workflowKey = defaultWorkflowKeyForTaskType(this, taskType)
      }
    },
    async createProject() {
      const labels = this.createDraft.labels
        .map((item) => item.trim())
        .filter(Boolean)
      this.saving = true
      try {
        const created = await backendClient.createProject({
          name: this.createDraft.name.trim(),
          taskType: this.createDraft.taskType,
          workflowKey: this.createDraft.workflowKey,
        })
        if (labels.length > 0) {
          const payload = await backendClient.updateProjectSettings(created.id, { labels })
          this.settings = payload.settings
          this.settingsChange = payload.change
        }
        await this.loadProjects()
        this.createDrawerOpen = false
        this.currentProject = this.projects.find((project) => project.id === created.id) ?? null
        return this.currentProject
      } finally {
        this.saving = false
      }
    },
    async saveSettings(projectId: number, patch: Partial<Pick<ProjectSettingsPayload, 'workflowKey' | 'labels'>>) {
      this.saving = true
      try {
        const payload = await backendClient.updateProjectSettings(projectId, patch)
        this.settings = payload.settings
        this.settingsChange = payload.change
        await this.loadProjects()
        this.currentProject = this.projects.find((project) => project.id === projectId) ?? null
      } finally {
        this.saving = false
      }
    },
  },
})
