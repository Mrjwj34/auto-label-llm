<template>
  <section class="section-panel">
    <header v-if="$slots.header || $slots.actions" class="section-panel-head">
      <div class="section-panel-title">
        <slot name="header" />
      </div>
      <div v-if="$slots.actions" class="section-panel-actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="section-panel-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.section-panel {
  border: 1px solid var(--line);
  background: var(--panel);
}

.section-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--line);
  padding: 16px 18px;
}

.section-panel-body {
  padding: 18px;
}

.section-panel-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-panel-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
