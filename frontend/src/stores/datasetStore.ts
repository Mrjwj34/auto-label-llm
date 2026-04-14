import { defineStore } from 'pinia'
import { backendClient } from '../backend/client'
import type { ProjectWorkspace } from '../backend/types'

function isFinal(status: string): boolean {
  return status === 'SUCCESS' || status === 'FAILED'
}

export const useDatasetStore = defineStore('dataset', {
  state: () => ({
    projectId: 0,
    loading: false,
    workspace: null as ProjectWorkspace | null,
    sortMode: 'review_queue' as 'review_queue' | 'latest_quality' | 'newest',
    pollHandle: 0 as number,
  }),
  getters: {
    sortedImages(state) {
      if (!state.workspace) return []
      const rows = [...state.workspace.images]
      if (state.sortMode === 'latest_quality') {
        return rows.sort((left, right) => (left.qualityScore ?? 1) - (right.qualityScore ?? 1))
      }
      if (state.sortMode === 'newest') {
        return rows.sort((left, right) => right.id - left.id)
      }
      return rows.sort((left, right) => {
        const leftScore = left.qualityScore ?? 1
        const rightScore = right.qualityScore ?? 1
        return leftScore - rightScore
      })
    },
  },
  actions: {
    stopPolling() {
      if (this.pollHandle) {
        window.clearInterval(this.pollHandle)
        this.pollHandle = 0
      }
    },
    async load(projectId: number) {
      this.projectId = projectId
      this.loading = true
      try {
        this.workspace = await backendClient.getProjectWorkspace(projectId)
      } finally {
        this.loading = false
      }
      if (this.workspace && !isFinal(this.workspace.task.status)) {
        this.ensurePolling()
      } else {
        this.stopPolling()
      }
    },
    ensurePolling() {
      if (this.pollHandle || !this.projectId) return
      this.pollHandle = window.setInterval(async () => {
        const next = await backendClient.getProjectWorkspace(this.projectId)
        this.workspace = next
        if (isFinal(next.task.status)) {
          this.stopPolling()
        }
      }, 720)
    },
    async startBatchAnnotate() {
      if (!this.projectId) return
      await backendClient.startBatchAnnotate(this.projectId)
      await this.load(this.projectId)
    },
  },
})
