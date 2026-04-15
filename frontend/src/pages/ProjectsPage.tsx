import { motion } from 'framer-motion'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api'
import type { ProjectListItem, ProjectMetaPayload } from '../types'
import { formatTime } from '../utils'

type ProjectsPageProps = {
  projects: ProjectListItem[]
  meta: ProjectMetaPayload | null
  reloadProjects: () => Promise<void>
  pushToast: (message: string, tone?: 'success' | 'danger' | 'info') => void
}

export function ProjectsPage({ projects, meta, reloadProjects, pushToast }: ProjectsPageProps) {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [taskType, setTaskType] = useState<'detection' | 'segmentation'>('detection')
  const [workflowKey, setWorkflowKey] = useState('')
  const [busy, setBusy] = useState(false)

  const availableWorkflows = useMemo(
    () => meta?.workflows.filter((workflow) => workflow.task_type === taskType) ?? [],
    [meta, taskType],
  )

  return (
    <motion.div className="workspace-page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <section className="section section-grid">
        <div className="section-head">
          <h2>项目列表</h2>
          <span>{projects.length} 个项目</span>
        </div>
        <div className="data-table project-table">
          <div className="table-head">
            <span>名称</span>
            <span>任务类型</span>
            <span>工作流</span>
            <span>创建时间</span>
            <span>操作</span>
          </div>
          <div className="table-body">
            {projects.map((project) => (
              <button
                className="table-row table-row-button"
                key={project.id}
                onClick={() => navigate(`/projects/${project.id}`)}
                type="button"
              >
                <span>{project.name}</span>
                <span>{project.task_type === 'detection' ? '检测' : '分割'}</span>
                <span>{project.workflow_key}</span>
                <span>{formatTime(project.created_at)}</span>
                <span className="row-actions">
                  <i>{project.task_family}</i>
                </span>
              </button>
            ))}
            {projects.length === 0 ? <div className="table-empty">暂无项目</div> : null}
          </div>
        </div>
      </section>

      <section className="section create-project-panel">
        <div className="section-head">
          <h2>新建项目</h2>
          <span>基于真实 workflow 元信息</span>
        </div>
        <div className="form-grid compact-two">
          <label className="field">
            <span>项目名称</span>
            <input onChange={(event) => setName(event.target.value)} placeholder="例如：工业缺陷分割" value={name} />
          </label>
          <label className="field">
            <span>任务类型</span>
            <select
              onChange={(event) => {
                const next = event.target.value as 'detection' | 'segmentation'
                setTaskType(next)
                setWorkflowKey(meta?.default_workflows[next] ?? '')
              }}
              value={taskType}
            >
              <option value="detection">检测</option>
              <option value="segmentation">分割</option>
            </select>
          </label>
          <label className="field full-span">
            <span>工作流</span>
            <select onChange={(event) => setWorkflowKey(event.target.value)} value={workflowKey}>
              <option value="">使用默认工作流</option>
              {availableWorkflows.map((workflow) => (
                <option key={workflow.key} value={workflow.key}>
                  {workflow.display_name} / {workflow.key}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="workflow-strip">
          {availableWorkflows.map((workflow) => (
            <div className={`workflow-chip ${workflow.key === workflowKey ? 'is-active' : ''}`} key={workflow.key}>
              <strong>{workflow.display_name}</strong>
              <span>{workflow.task_family}</span>
              <span>{workflow.capabilities.join(' / ')}</span>
            </div>
          ))}
        </div>
        <div className="toolbar">
          <button
            className="primary-btn"
            disabled={busy || !name.trim()}
            onClick={async () => {
              try {
                setBusy(true)
                const created = await api.createProject({
                  name: name.trim(),
                  task_type: taskType,
                  workflow_key: workflowKey || undefined,
                })
                await reloadProjects()
                pushToast('项目已创建', 'success')
                navigate(`/projects/${created.id}`)
              } catch (error) {
                pushToast(error instanceof Error ? error.message : '创建失败', 'danger')
              } finally {
                setBusy(false)
              }
            }}
            type="button"
          >
            创建项目
          </button>
        </div>
      </section>
    </motion.div>
  )
}
