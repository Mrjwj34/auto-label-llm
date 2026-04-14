<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

const props = defineProps<{
  collapsed?: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

const route = useRoute()

function isProjectRoute() {
  return route.path.startsWith('/projects')
}
</script>

<template>
  <aside class="shell-sidebar" :class="{ collapsed: props.collapsed }" :aria-hidden="props.collapsed ? 'true' : undefined">
    <div class="shell-sidebar-head">
      <div class="shell-brand">
        <div class="shell-brand-mark">AL</div>
        <div class="shell-brand-copy">
          <div class="shell-brand-title">自动标注</div>
          <div class="shell-brand-sub">工作流控制台</div>
        </div>
      </div>

      <button type="button" class="shell-toggle" @click="emit('toggle')">收起</button>
    </div>

    <nav class="shell-nav">
      <RouterLink class="shell-link" :class="{ active: isProjectRoute() }" to="/projects">项目</RouterLink>
      <RouterLink class="shell-link" :class="{ active: route.path === '/settings' }" to="/settings">全局设置</RouterLink>
      <RouterLink class="shell-link" :class="{ active: route.path === '/diagnostics' }" to="/diagnostics">诊断</RouterLink>
    </nav>
  </aside>
</template>

<style scoped>
.shell-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  width: 220px;
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  flex-direction: column;
  gap: 24px;
  border-right: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(247, 250, 255, 0.98) 0%, rgba(239, 245, 255, 0.98) 100%);
  padding: 18px 16px;
  overflow-y: auto;
  transition:
    opacity 220ms cubic-bezier(0.22, 1, 0.36, 1),
    transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
    visibility 220ms step-end;
}

.shell-sidebar.collapsed {
  visibility: hidden;
  opacity: 0;
  transform: translateX(-24px);
  pointer-events: none;
}

.shell-sidebar-head {
  display: grid;
  gap: 12px;
}

.shell-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.shell-brand-mark {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  background: var(--accent);
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.shell-brand-copy {
  min-width: 0;
}

.shell-brand-title {
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.shell-brand-sub {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.shell-toggle {
  min-width: 56px;
  padding-inline: 10px;
  justify-self: start;
}

.shell-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.shell-link {
  border-left: 2px solid transparent;
  padding: 12px 14px;
  color: var(--text-soft);
  text-decoration: none;
  background: transparent;
  transition:
    border-color 160ms ease,
    color 160ms ease,
    background-color 160ms ease;
}

.shell-link:hover {
  background: rgba(11, 95, 255, 0.05);
  color: var(--text-strong);
}

.shell-link.active {
  border-color: var(--accent);
  background:
    linear-gradient(90deg, rgba(11, 95, 255, 0.12) 0%, rgba(11, 95, 255, 0.04) 100%);
  color: var(--accent);
  font-weight: 600;
}

@media (max-width: 960px) {
  .shell-sidebar,
  .shell-sidebar.collapsed {
    position: static;
    width: auto;
    height: auto;
    visibility: visible;
    opacity: 1;
    transform: none;
    pointer-events: auto;
    overflow: visible;
    border-right: none;
    border-bottom: 1px solid var(--line);
  }

  .shell-toggle {
    display: none;
  }
}
</style>
