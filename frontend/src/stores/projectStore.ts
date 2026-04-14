import { defineStore } from 'pinia'
import { backendClient } from '../backend/client'
import type { ProjectMetaPayload, ProjectSettingsPayload, ProjectSummary, SettingsChange, TaskType, WorkflowDefinition } from '../backend/types'

type CreateDraft = {
  name: string
  workflowKey: string
  labels: string[]
}

function defaultWorkflowKey(meta: Pick<ProjectMetaPayload, 'defaultWorkflows' | 'workflows'>): string {
  return meta.workflows[0]?.key ?? meta.defaultWorkflows.segmentation ?? meta.defaultWorkflows.detection ?? ''
}

function workflowForKey(meta: Pick<ProjectMetaPayload, 'workflows'>, workflowKey: string): WorkflowDefinition | null {
  return meta.workflows.find((workflow) => workflow.key === workflowKey) ?? null
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
      workflowKey: 'generic_instance_segmentation',
      labels: [],
    } as CreateDraft,
  }),
  getters: {
    filteredProjects(state) {
      const query = state.search.trim().toLowerCase()
      return state.projects.filter((project) => {
        const workflowName = state.workflows.find((workflow) => workflow.key === project.workflowKey)?.displayName.toLowerCase() ?? ''
        const matchesWorkflow = state.workflowFilter === 'all' || project.workflowKey === state.workflowFilter
        const matchesQuery =
          query.length === 0 ||
          project.name.toLowerCase().includes(query) ||
          project.workflowKey.toLowerCase().includes(query) ||
          project.taskFamily.toLowerCase().includes(query) ||
          workflowName.includes(query)
        return matchesWorkflow && matchesQuery
      })
    },
    selectedWorkflow(state) {
      return state.workflows.find((workflow) => workflow.key === state.createDraft.workflowKey) ?? null
    },
    availableCreateWorkflows(state) {
      return state.workflows
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
        if (!this.createDraft.workflowKey || !this.workflows.some((workflow) => workflow.key === this.createDraft.workflowKey)) {
          this.createDraft.workflowKey = defaultWorkflowKey(this)
        }
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
      const workflow = workflowForKey(this, workflowKey ?? defaultWorkflowKey(this)) ?? workflowForKey(this, defaultWorkflowKey(this))
      this.createDrawerOpen = true
      this.createDraft = {
        name: '',
        workflowKey: workflow?.key ?? defaultWorkflowKey(this),
        labels: [],
      }
    },
    closeCreateDrawer() {
      this.createDrawerOpen = false
    },
    async createProject() {
      const labels = this.createDraft.labels
        .map((item) => item.trim())
        .filter(Boolean)
      const workflow = workflowForKey(this, this.createDraft.workflowKey) ?? workflowForKey(this, defaultWorkflowKey(this))
      if (!workflow) {
        throw new Error('No workflow available for project creation')
      }
      this.saving = true
      try {
        const created = await backendClient.createProject({
          name: this.createDraft.name.trim(),
          taskType: workflow.taskType,
          workflowKey: workflow.key,
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
    async saveSettings(projectId: number, patch: Partial<Pick<ProjectSettingsPayload, 'workflowKey' | 'labels' | 'activeModelTag'>>) {
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
    async activateModel(projectId: number, modelTag: string) {
      this.saving = true
      try {
        const payload = await backendClient.activateProjectModel(projectId, modelTag)
        this.settings = payload.settings
        this.settingsChange = null
        await this.loadProjects()
        this.currentProject = this.projects.find((project) => project.id === projectId) ?? null
        return payload.message
      } finally {
        this.saving = false
      }
    },
  },
})
