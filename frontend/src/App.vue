<script setup lang="ts">
import ShellSidebar from './components/ShellSidebar.vue'
</script>

<template>
  <div class="app-shell">
    <ShellSidebar />
    <main class="app-main">
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
  grid-template-columns: 220px minmax(0, 1fr);
}

.app-main {
  min-width: 0;
}

@media (max-width: 960px) {
  .app-shell {
    grid-template-columns: 1fr;
  }
}
</style>
