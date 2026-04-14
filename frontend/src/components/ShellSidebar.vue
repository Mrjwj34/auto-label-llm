<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()

function isProjectRoute() {
  return route.path.startsWith('/projects')
}
</script>

<template>
  <aside class="shell-sidebar">
    <div class="shell-brand">
      <div class="shell-brand-mark">AL</div>
      <div class="shell-brand-copy">
        <div class="shell-brand-title">自动标注</div>
        <div class="shell-brand-sub">工作流控制台</div>
      </div>
    </div>

    <nav class="shell-nav">
      <RouterLink class="shell-link" :class="{ active: isProjectRoute() }" to="/projects">项目</RouterLink>
      <RouterLink class="shell-link" :class="{ active: route.path === '/diagnostics' }" to="/diagnostics">诊断</RouterLink>
    </nav>
  </aside>
</template>

<style scoped>
.shell-sidebar {
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  gap: 28px;
  border-right: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 22px 18px;
}

.shell-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.shell-brand-mark {
  display: grid;
  height: 36px;
  width: 36px;
  place-items: center;
  background: var(--accent);
  color: #fff;
  font-weight: 700;
}

.shell-brand-title {
  color: var(--text-strong);
  font-size: 18px;
  font-weight: 700;
}

.shell-brand-sub {
  color: var(--text-muted);
  font-size: 12px;
}

.shell-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.shell-link {
  border-left: 2px solid transparent;
  padding: 10px 12px;
  color: var(--text-soft);
  text-decoration: none;
  transition:
    border-color 160ms ease,
    color 160ms ease,
    background-color 160ms ease,
    transform 160ms ease;
}

.shell-link:hover {
  background: rgba(11, 95, 255, 0.06);
  color: var(--text-strong);
  transform: translateX(2px);
}

.shell-link.active {
  border-color: var(--accent);
  background: rgba(11, 95, 255, 0.08);
  color: var(--accent);
  font-weight: 600;
}
</style>
