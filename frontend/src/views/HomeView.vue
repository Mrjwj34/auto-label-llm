<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { API_BASE_URL, api } from '../api/http'

type BackendState = 'unknown' | 'ok' | 'error'

const backendState = ref<BackendState>('unknown')
const backendMessage = ref<string>('')

async function checkBackend() {
  backendState.value = 'unknown'
  backendMessage.value = ''
  try {
    const resp = await api.get('/healthz')
    backendState.value = 'ok'
    backendMessage.value = JSON.stringify(resp.data, null, 2)
  } catch (err: any) {
    backendState.value = 'error'
    backendMessage.value = err?.message ? String(err.message) : String(err)
  }
}

onMounted(() => {
  void checkBackend()
})
</script>

<template>
  <section class="panel">
    <h1>开发面板</h1>

    <div class="row">
      <div class="label">API Base URL</div>
      <div class="value">{{ API_BASE_URL }}</div>
    </div>

    <div class="row">
      <div class="label">Backend</div>
      <div class="value">
        <span class="pill" :class="backendState">{{ backendState }}</span>
      </div>
    </div>

    <div class="actions">
      <button class="btn" type="button" @click="checkBackend">重新检测</button>
    </div>

    <details class="details" open>
      <summary>返回内容 / 错误信息</summary>
      <pre class="pre">{{ backendMessage || '(empty)' }}</pre>
    </details>
  </section>
</template>

<style scoped>
.panel {
  max-width: 900px;
  margin: 0 auto;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 18px 12px;
}

.row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.08);
}

.label {
  width: 140px;
  opacity: 0.75;
}

.value {
  flex: 1;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 13px;
}

.actions {
  padding: 14px 0 10px;
}

.btn {
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  padding: 8px 12px;
  border-radius: 10px;
}

.btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.pill.ok {
  border-color: rgba(44, 190, 78, 0.45);
}
.pill.error {
  border-color: rgba(248, 81, 73, 0.45);
}

.details {
  margin-top: 12px;
}

.pre {
  margin-top: 10px;
  background: rgba(0, 0, 0, 0.25);
  padding: 12px;
  border-radius: 10px;
  overflow: auto;
}
</style>

