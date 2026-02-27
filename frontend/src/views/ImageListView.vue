<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API_BASE_URL, api } from '../api/http'

type ImageRow = {
  id: number
  filename: string
  width: number | null
  height: number | null
  split: string
  status: string
  quality_score: number | null
  file_url: string
}

const route = useRoute()
const router = useRouter()

const projectId = computed(() => Number(route.params.projectId))

const loading = ref(false)
const error = ref<string>('')
const images = ref<ImageRow[]>([])

const uploading = ref(false)
const selectedFiles = ref<File[]>([])

const canUpload = computed(() => selectedFiles.value.length > 0 && !uploading.value)

function imageSrc(img: ImageRow): string {
  const base = API_BASE_URL.replace(/\/$/, '')
  const path = img.file_url.startsWith('/') ? img.file_url : `/${img.file_url}`
  return `${base}${path}`
}

async function fetchImages() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  loading.value = true
  error.value = ''
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/images`)
    images.value = resp.data?.data ?? []
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    loading.value = false
  }
}

function onPickFiles(ev: Event) {
  const input = ev.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  selectedFiles.value = files
}

async function upload() {
  if (!canUpload.value) return
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    for (const f of selectedFiles.value) form.append('files[]', f)
    await api.post(`/api/projects/${projectId.value}/images/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    selectedFiles.value = []
    await fetchImages()
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    uploading.value = false
  }
}

function backToProjects() {
  router.push({ name: 'projects' })
}

onMounted(() => {
  void fetchImages()
})

watch(projectId, () => {
  void fetchImages()
})
</script>

<template>
  <section class="wrap">
    <header class="header">
      <div>
        <h1>图片</h1>
        <div class="sub">
          Project #{{ projectId }} · 上传图片后即可进入下一阶段（自动标注/纠错）。
        </div>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" @click="backToProjects">返回项目</button>
        <button class="btn" type="button" :disabled="loading" @click="fetchImages">刷新</button>
      </div>
    </header>

    <div class="card">
      <div class="row">
        <input class="input" type="file" multiple accept="image/*" @change="onPickFiles" />
        <button class="btn primary" type="button" :disabled="!canUpload" @click="upload">
          {{ uploading ? '上传中…' : '上传' }}
        </button>
      </div>
      <div v-if="selectedFiles.length > 0" class="hint">已选择 {{ selectedFiles.length }} 个文件</div>
      <div v-if="error" class="error">{{ error }}</div>
    </div>

    <div class="list">
      <div v-if="loading" class="hint">加载中…</div>
      <div v-else-if="images.length === 0" class="hint">暂无图片，先上传。</div>
      <div v-else class="grid">
        <article v-for="img in images" :key="img.id" class="item">
          <div class="thumb">
            <img :src="imageSrc(img)" :alt="img.filename" loading="lazy" />
          </div>
          <div class="title">{{ img.filename }}</div>
          <div class="meta">
            <span>#{{ img.id }}</span>
            <span class="dot">•</span>
            <span>{{ img.width }}×{{ img.height }}</span>
          </div>
          <div class="meta muted">
            <span>split: {{ img.split }}</span>
            <span class="dot">•</span>
            <span>status: {{ img.status }}</span>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wrap {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.sub {
  opacity: 0.7;
  margin-top: 6px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  padding: 14px;
}

.row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.input {
  flex: 1;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(0, 0, 0, 0.15);
  color: inherit;
}

.list {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 16px;
}

.hint {
  opacity: 0.75;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.item {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  padding: 12px;
}

.thumb {
  width: 100%;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.title {
  margin-top: 10px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  opacity: 0.8;
  font-size: 13px;
  margin-top: 4px;
}

.meta.muted {
  opacity: 0.6;
}

.dot {
  opacity: 0.6;
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

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.btn.primary {
  border-color: rgba(99, 102, 241, 0.55);
}

.error {
  margin-top: 10px;
  color: rgba(248, 81, 73, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 13px;
}
</style>
