import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api } from './api'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { SystemPage } from './pages/SystemPage'
import type { ProjectListItem, ProjectMetaPayload } from './types'
import { clsx } from './utils'

type Toast = {
  id: number
  message: string
  tone: 'success' | 'danger' | 'info'
}

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectListItem[]>([])
  const [meta, setMeta] = useState<ProjectMetaPayload | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])

  const pushToast = (message: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.floor(Math.random() * 1000)
    setToasts((current) => [...current, { id, message, tone }])
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id))
    }, 2800)
  }

  const reloadProjects = async () => {
    try {
      const [nextProjects, nextMeta] = await Promise.all([api.listProjects(), api.getProjectMeta()])
      setProjects(nextProjects)
      setMeta(nextMeta)
      if (location.pathname === '/' && nextProjects[0]) {
        navigate(`/projects/${nextProjects[0].id}`, { replace: true })
      }
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '项目列表加载失败', 'danger')
    }
  }

  useEffect(() => {
    void reloadProjects()
  }, [])

  const projectRows = useMemo(
    () =>
      projects.map((project) => ({
        id: project.id,
        title: project.name,
        detail: `${project.task_type === 'detection' ? '检测' : '分割'} / ${project.workflow_key}`,
      })),
    [projects],
  )

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-kicker">Auto Label LLM</span>
          <strong>自动标注系统</strong>
        </div>
        <nav className="main-nav">
          <NavLink className={({ isActive }) => clsx('nav-link', isActive && 'is-active')} to="/projects">
            项目
          </NavLink>
          <NavLink className={({ isActive }) => clsx('nav-link', isActive && 'is-active')} to="/system">
            全局设置
          </NavLink>
        </nav>
        <div className="sidebar-section">
          <div className="sidebar-title">项目导航</div>
          <div className="project-nav-list">
            {projectRows.map((row) => (
              <NavLink
                className={({ isActive }) => clsx('project-link', isActive && 'is-active')}
                key={row.id}
                to={`/projects/${row.id}`}
              >
                <strong>{row.title}</strong>
                <span>{row.detail}</span>
              </NavLink>
            ))}
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div className="header-route">
            <strong>{location.pathname.startsWith('/system') ? '全局设置' : '项目工作区'}</strong>
            <span>{projects.length} 个项目</span>
          </div>
          <button className="header-action" onClick={() => void reloadProjects()} type="button">
            刷新
          </button>
        </header>

        <AnimatePresence mode="wait">
          <motion.div key={location.pathname} className="workspace-body" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <Routes>
              <Route
                element={<ProjectsPage meta={meta} projects={projects} pushToast={pushToast} reloadProjects={reloadProjects} />}
                path="/projects"
              />
              <Route
                element={<ProjectPage projects={projects} pushToast={pushToast} reloadProjects={reloadProjects} />}
                path="/projects/:projectId"
              />
              <Route element={<SystemPage pushToast={pushToast} />} path="/system" />
              <Route
                element={<ProjectsPage meta={meta} projects={projects} pushToast={pushToast} reloadProjects={reloadProjects} />}
                path="*"
              />
            </Routes>
          </motion.div>
        </AnimatePresence>
      </main>

      <div className="toast-stack">
        {toasts.map((toast) => (
          <div className={clsx('toast', `tone-${toast.tone}`)} key={toast.id}>
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  )
}
