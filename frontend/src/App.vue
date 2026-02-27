<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <router-link class="brand-link" to="/">Auto Labeling System</router-link>
      </div>
      <nav class="nav">
        <router-link class="link" to="/">Projects</router-link>
        <router-link class="link" to="/dev">Dev</router-link>
      </nav>
    </header>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand {
  font-weight: 650;
  letter-spacing: 0.2px;
}

.brand-link {
  color: inherit;
  text-decoration: none;
}

.nav {
  display: flex;
  gap: 12px;
}

.link {
  color: inherit;
  text-decoration: none;
  opacity: 0.85;
}

.link:hover {
  opacity: 1;
  text-decoration: underline;
}

.content {
  flex: 1;
  padding: 20px;
}
</style>
