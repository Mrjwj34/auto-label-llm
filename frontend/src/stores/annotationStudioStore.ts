import { defineStore } from 'pinia'
import { backendClient } from '../backend/client'
import type { ImageDetail, InteractionMode, ReviewQueueItem, WorkflowDefinition } from '../backend/types'

export const useAnnotationStudioStore = defineStore('annotationStudio', {
  state: () => ({
    projectId: 0,
    loading: false,
    projectName: '',
    workflow: null as WorkflowDefinition | null,
    queue: [] as ReviewQueueItem[],
    image: null as ImageDetail | null,
    selectedAnnotationId: 0,
    mode: 'bbox' as InteractionMode,
  }),
  getters: {
    selectedAnnotation(state) {
      return state.image?.annotations.find((annotation) => annotation.id === state.selectedAnnotationId) ?? null
    },
    supportsPointMode(state) {
      return Boolean(state.workflow?.supportsPointRefine)
    },
  },
  actions: {
    async load(projectId: number, imageId?: number) {
      this.projectId = projectId
      this.loading = true
      try {
        const payload = await backendClient.getAnnotationStudio(projectId, imageId)
        this.projectName = payload.project.name
        this.workflow = payload.workflow
        this.queue = payload.queue
        this.image = payload.image
        this.selectedAnnotationId = payload.image?.annotations[0]?.id ?? 0
        if (!this.workflow.supportsPointRefine && this.mode === 'point') {
          this.mode = 'bbox'
        }
      } finally {
        this.loading = false
      }
    },
    selectImage(imageId: number) {
      if (!this.projectId) return
      void this.load(this.projectId, imageId)
    },
    selectAnnotation(annotationId: number) {
      this.selectedAnnotationId = annotationId
    },
    setMode(mode: InteractionMode) {
      if (mode === 'point' && !this.supportsPointMode) return
      this.mode = mode
    },
    async confirmSelected() {
      if (!this.projectId || !this.image || !this.selectedAnnotationId) return
      this.image = await backendClient.confirmAnnotation(this.projectId, this.image.id, this.selectedAnnotationId)
      this.selectedAnnotationId = this.image.annotations[0]?.id ?? 0
      await this.load(this.projectId, this.image.id)
    },
    async deleteSelected() {
      if (!this.projectId || !this.image || !this.selectedAnnotationId) return
      this.image = await backendClient.deleteAnnotation(this.projectId, this.image.id, this.selectedAnnotationId)
      this.selectedAnnotationId = this.image.annotations[0]?.id ?? 0
      await this.load(this.projectId, this.image.id)
    },
    nextImageId(): number | null {
      if (!this.image) return this.queue[0]?.imageId ?? null
      const currentIndex = this.queue.findIndex((item) => item.imageId === this.image?.id)
      return this.queue[currentIndex + 1]?.imageId ?? null
    },
  },
})
