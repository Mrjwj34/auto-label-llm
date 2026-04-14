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
  overflow: hidden;
  transition:
    border-color 220ms ease,
    background-color 220ms ease,
    transform 220ms cubic-bezier(0.22, 1, 0.36, 1);
  animation: section-panel-enter 280ms cubic-bezier(0.22, 1, 0.36, 1);
}

.section-panel:hover {
  border-color: #b8cbe3;
  transform: translateY(-2px);
}

.section-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--line);
  padding: 12px 16px;
  background: var(--panel-soft);
}

.section-panel-body {
  padding: 16px;
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

@keyframes section-panel-enter {
  from {
    opacity: 0;
    transform: translateY(12px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
