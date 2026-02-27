<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">Auto Labeling System</div>
      <nav class="nav">
        <a class="link" href="/">Home</a>
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
