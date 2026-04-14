<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ShellSidebar from './components/ShellSidebar.vue'

const SIDEBAR_STORAGE_KEY = 'app-sidebar-collapsed'
const DESKTOP_BREAKPOINT_QUERY = '(max-width: 960px)'

const sidebarCollapsed = ref(false)
const isCompactLayout = ref(false)

let mediaQueryList: MediaQueryList | null = null

const effectiveSidebarCollapsed = computed(() => !isCompactLayout.value && sidebarCollapsed.value)

function syncLayoutMode() {
  isCompactLayout.value = mediaQueryList?.matches ?? false
}

function toggleSidebar() {
  if (isCompactLayout.value) return
  sidebarCollapsed.value = !sidebarCollapsed.value
}

onMounted(() => {
  if (typeof window === 'undefined') return

  sidebarCollapsed.value = window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
  mediaQueryList = window.matchMedia(DESKTOP_BREAKPOINT_QUERY)
  syncLayoutMode()
  mediaQueryList.addEventListener('change', syncLayoutMode)
})

onBeforeUnmount(() => {
  mediaQueryList?.removeEventListener('change', syncLayoutMode)
  mediaQueryList = null
})

watch(sidebarCollapsed, (value) => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value))
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': effectiveSidebarCollapsed }">
    <ShellSidebar :collapsed="effectiveSidebarCollapsed" @toggle="toggleSidebar" />

    <main class="app-main">
      <button v-if="effectiveSidebarCollapsed" type="button" class="app-sidebar-trigger" aria-label="展开导航" @click="toggleSidebar">导航</button>

      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  min-height: 100vh;
  min-height: 100dvh;
  grid-template-columns: 220px minmax(0, 1fr);
  align-items: start;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(237, 243, 251, 0.96) 48%, rgba(229, 238, 250, 1) 100%);
  transition: grid-template-columns 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

.app-shell.sidebar-collapsed {
  grid-template-columns: 0 minmax(0, 1fr);
}

.app-main {
  position: relative;
  display: grid;
  align-content: start;
  min-width: 0;
  min-height: 100vh;
  min-height: 100dvh;
}

.app-sidebar-trigger {
  position: sticky;
  top: 18px;
  left: 0;
  justify-self: start;
  margin: 18px 0 -52px 20px;
  z-index: 40;
  padding: 10px 12px;
  border-color: #b9cde7;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(10px);
  white-space: nowrap;
}

.app-shell.sidebar-collapsed :deep(.page-frame) {
  padding-left: 116px;
}

@media (max-width: 960px) {
  .app-shell,
  .app-shell.sidebar-collapsed {
    grid-template-columns: 1fr;
  }

  .app-main {
    min-height: auto;
  }

  .app-sidebar-trigger {
    display: none;
  }

  .app-shell.sidebar-collapsed :deep(.page-frame) {
    padding-left: 18px;
  }
}
</style>
