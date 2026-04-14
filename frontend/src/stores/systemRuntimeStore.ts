import { defineStore } from 'pinia'
import { backendClient } from '../backend/client'
import type { DiagnosticsSnapshot, RuntimeSettings, SettingsChange, SystemConfig, SystemSettingsPayload } from '../backend/types'

function toRuntimeSummary(config: SystemConfig): RuntimeSettings {
  return {
    activeProfile: config.activeProfile,
    annotationBackend: config.runtime.annotationBackend,
    modelName: config.runtime.modelName,
    requestTimeoutSeconds: config.runtime.llmRequestTimeoutSeconds,
    maxRetries: config.runtime.llmMaxRetries,
    reloadRequiredPaths: [...config.settings._meta.reloadRequiredPaths],
    profiles: config.profiles.map((profile) => ({ ...profile })),
  }
}

export const useSystemRuntimeStore = defineStore('systemRuntime', {
  state: () => ({
    loading: false,
    saving: false,
    runningSelftest: false,
    runtime: null as RuntimeSettings | null,
    systemConfig: null as SystemConfig | null,
    systemSettings: null as SystemSettingsPayload | null,
    settingsChange: null as SettingsChange | null,
    diagnostics: null as DiagnosticsSnapshot | null,
  }),
  actions: {
    async loadRuntime() {
      this.loading = true
      try {
        const [config, settings] = await Promise.all([backendClient.getSystemConfig(), backendClient.getSystemSettings()])
        this.systemConfig = config
        this.systemSettings = settings
        this.runtime = toRuntimeSummary(config)
      } finally {
        this.loading = false
      }
    },
    async loadDiagnostics() {
      this.loading = true
      try {
        this.diagnostics = await backendClient.getDiagnostics()
      } finally {
        this.loading = false
      }
    },
    async hydrate() {
      await Promise.all([this.loadRuntime(), this.loadDiagnostics()])
    },
    async activateProfile(profileName: string) {
      this.systemConfig = await backendClient.activateSystemProfile(profileName)
      this.systemSettings = this.systemConfig.settings
      this.runtime = toRuntimeSummary(this.systemConfig)
      this.settingsChange = null
      this.diagnostics = await backendClient.getDiagnostics()
    },
    async saveSystemSettings(patch: Partial<SystemSettingsPayload>) {
      this.saving = true
      try {
        const payload = await backendClient.updateSystemSettings(patch)
        this.systemSettings = payload.settings
        this.settingsChange = payload.change
        this.systemConfig = await backendClient.getSystemConfig()
        this.runtime = toRuntimeSummary(this.systemConfig)
      } finally {
        this.saving = false
      }
    },
    async runSelftest() {
      this.runningSelftest = true
      try {
        this.diagnostics = await backendClient.runSelftest()
      } finally {
        this.runningSelftest = false
      }
    },
  },
})
