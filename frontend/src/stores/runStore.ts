import { defineStore } from 'pinia'
import { backendClient } from '../backend/client'
import type { EvaluationRun, FailureSample, TrainJob } from '../backend/types'

function hasLiveStatus(status: string): boolean {
  return status === 'RUNNING' || status === 'QUEUED'
}

export const useRunStore = defineStore('run', {
  state: () => ({
    projectId: 0,
    loading: false,
    trainJobs: [] as TrainJob[],
    evaluations: [] as EvaluationRun[],
    failureSamples: [] as FailureSample[],
    pollHandle: 0 as number,
  }),
  getters: {
    latestTrain(state) {
      return state.trainJobs[0] ?? null
    },
    latestEvaluation(state) {
      return state.evaluations[0] ?? null
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
        const [trainJobs, evaluationPayload] = await Promise.all([
          backendClient.listTrainJobs(projectId),
          backendClient.listEvaluations(projectId),
        ])
        this.trainJobs = trainJobs
        this.evaluations = evaluationPayload.runs
        this.failureSamples = evaluationPayload.failures
      } finally {
        this.loading = false
      }
      const hasLiveRun = this.trainJobs.some((job) => hasLiveStatus(job.status)) || this.evaluations.some((run) => hasLiveStatus(run.status))
      if (hasLiveRun) {
        this.ensurePolling()
      } else {
        this.stopPolling()
      }
    },
    ensurePolling() {
      if (this.pollHandle || !this.projectId) return
      this.pollHandle = window.setInterval(async () => {
        await this.load(this.projectId)
      }, 900)
    },
    async startTrain() {
      if (!this.projectId) return
      this.trainJobs = await backendClient.startTrain(this.projectId)
      this.ensurePolling()
    },
    async startEvaluation() {
      if (!this.projectId) return
      const payload = await backendClient.startEvaluation(this.projectId)
      this.evaluations = payload.runs
      this.failureSamples = payload.failures
      this.ensurePolling()
    },
  },
})
