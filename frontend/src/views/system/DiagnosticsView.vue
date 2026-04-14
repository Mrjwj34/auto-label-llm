<script setup lang="ts">
import { onMounted } from 'vue'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useSystemRuntimeStore } from '../../stores/systemRuntimeStore'
import { cacheStatusText, selftestNameText, selftestStatusText, serviceHealthText, serviceNameText } from '../../utils/uiText'

const systemStore = useSystemRuntimeStore()

onMounted(() => {
  if (!systemStore.diagnostics) {
    void systemStore.hydrate()
  }
})
</script>

<template>
  <div class="page-frame">
    <header class="page-header">
      <div>
        <h1 class="page-title">诊断</h1>
        <div class="page-meta mono">上次自检={{ systemStore.diagnostics?.lastRunAt ?? '-' }}</div>
      </div>
      <div>
        <button class="primary" :disabled="systemStore.runningSelftest" @click="systemStore.runSelftest">
          {{ systemStore.runningSelftest ? '执行中...' : '执行自检' }}
        </button>
      </div>
    </header>

    <div class="system-grid">
      <SectionPanel>
        <template #header><strong>服务健康</strong></template>
        <div class="diagnostics-stack">
          <div v-for="service in systemStore.diagnostics?.services ?? []" :key="service.name" class="diagnostics-row mono">
            <span>{{ serviceNameText(service.name) }}</span>
            <StatusChip :label="serviceHealthText(service.status)" :tone="service.status === 'healthy' ? 'success' : service.status === 'degraded' ? 'warning' : 'danger'" />
          </div>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>自检</strong></template>
        <div class="diagnostics-stack">
          <div v-for="check in systemStore.diagnostics?.selftest ?? []" :key="check.name" class="diagnostics-row mono">
            <span>{{ selftestNameText(check.name) }}</span>
            <StatusChip :label="selftestStatusText(check.status)" :tone="check.status === 'PASS' ? 'success' : check.status === 'TIMEOUT' ? 'warning' : check.status === 'FAIL' ? 'danger' : 'neutral'" />
          </div>
        </div>
      </SectionPanel>

      <SectionPanel>
        <template #header><strong>缓存</strong></template>
        <div class="diagnostics-stack mono">
          <div v-for="cache in systemStore.diagnostics?.caches ?? []" :key="cache.name" class="diagnostics-row">
            <span>{{ cache.name }}</span>
            <span>{{ cacheStatusText(cache.status) }}</span>
          </div>
        </div>
      </SectionPanel>
    </div>
  </div>
</template>

<style scoped>
.system-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.diagnostics-stack {
  display: grid;
  gap: 10px;
}

.diagnostics-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid rgba(94, 111, 138, 0.14);
  padding: 10px 0;
}

@media (max-width: 1080px) {
  .system-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .system-grid {
    grid-template-columns: 1fr;
  }
}
</style>
