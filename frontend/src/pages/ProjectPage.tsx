import { motion } from 'framer-motion'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../api'
import { ImageStage } from '../components/ImageStage'
import { TaskTicker } from '../components/TaskTicker'
import type {
  AnnotationRecord,
  EvaluationComparePayload,
  EvaluationReport,
  EvaluationRunRecord,
  FinetuneJobRecord,
  ImageRecord,
  ProjectListItem,
  ProjectSettingsPayload,
} from '../types'
import { clsx, downloadBlob, formatNumber, formatPercent, formatTime, toLabelList } from '../utils'

type ProjectPageProps = {
  projects: ProjectListItem[]
  reloadProjects: () => Promise<void>
  pushToast: (message: string, tone?: 'success' | 'danger' | 'info') => void
}

type WorkspaceTab = 'annotate' | 'evaluate' | 'finetune' | 'settings'

export function ProjectPage({ projects, reloadProjects, pushToast }: ProjectPageProps) {
  const params = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const projectId = Number(params.projectId)
  const project = useMemo(() => projects.find((item) => item.id === projectId) ?? null, [projectId, projects])

  const [tab, setTab] = useState<WorkspaceTab>('annotate')
  const [settings, setSettings] = useState<ProjectSettingsPayload | null>(null)
  const [images, setImages] = useState<ImageRecord[]>([])
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null)
  const [annotations, setAnnotations] = useState<AnnotationRecord[]>([])
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<number | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [drawEnabled, setDrawEnabled] = useState(false)
  const [draftBox, setDraftBox] = useState<[number, number, number, number] | null>(null)
  const [draftPoints, setDraftPoints] = useState<Array<{ x: number; y: number; label: 0 | 1 }>>([])
  const [pointMode, setPointMode] = useState<0 | 1 | null>(null)
  const [labelDraft, setLabelDraft] = useState('')
  const [labelText, setLabelText] = useState('')
  const [finetuneJobs, setFinetuneJobs] = useState<FinetuneJobRecord[]>([])
  const [selectedJobLog, setSelectedJobLog] = useState('')
  const [evaluations, setEvaluations] = useState<EvaluationRunRecord[]>([])
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [report, setReport] = useState<EvaluationReport | null>(null)
  const [compare, setCompare] = useState<EvaluationComparePayload | null>(null)
  const [busy, setBusy] = useState(false)

  const selectedImage = useMemo(() => images.find((item) => item.id === selectedImageId) ?? null, [images, selectedImageId])
  const selectedAnnotation = useMemo(
    () => annotations.find((item) => item.id === selectedAnnotationId) ?? null,
    [annotations, selectedAnnotationId],
  )

  const loadProject = async () => {
    if (!projectId || Number.isNaN(projectId)) return
    try {
      const [nextSettings, nextImages, nextJobs, nextEvals] = await Promise.all([
        api.getProjectSettings(projectId),
        api.listImages(projectId),
        api.listFinetuneJobs(projectId),
        api.listEvaluations(projectId),
      ])
      setSettings(nextSettings)
      setImages(nextImages)
      setLabelText(nextSettings.labels.join('\n'))
      setFinetuneJobs(nextJobs)
      setEvaluations(nextEvals)
      setLabelDraft(nextSettings.labels[0] ?? '')
      const fallbackImage = nextImages[0]?.id ?? null
      setSelectedImageId((current) => (current && nextImages.some((item) => item.id === current) ? current : fallbackImage))
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '项目加载失败', 'danger')
    }
  }

  const loadAnnotations = async (imageId: number | null) => {
    if (!imageId) {
      setAnnotations([])
      return
    }
    try {
      const next = await api.listAnnotations(imageId)
      setAnnotations(next)
      setSelectedAnnotationId((current) => (current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null))
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '标注加载失败', 'danger')
    }
  }

  useEffect(() => {
    void loadProject()
  }, [projectId])

  useEffect(() => {
    void loadAnnotations(selectedImageId)
  }, [selectedImageId])

  useEffect(() => {
    const selectedRun = evaluations.find((item) => item.id === selectedRunId)
    if (!selectedRun || selectedRun.status !== 'done') {
      setReport(null)
      setCompare(null)
      return
    }
    const loadReport = async () => {
      try {
        const [nextReport, nextCompare] = await Promise.all([
          api.getEvaluationReport(selectedRun.id),
          api.compareEvaluation(selectedRun.id).catch(() => null),
        ])
        setReport(nextReport)
        setCompare(nextCompare)
      } catch (error) {
        pushToast(error instanceof Error ? error.message : '评估报告加载失败', 'danger')
      }
    }
    void loadReport()
  }, [evaluations, pushToast, selectedRunId])

  if (!project) {
    return (
      <div className="loading-panel">
        <span>项目不存在或已删除</span>
        <button onClick={() => navigate('/projects')} type="button">
          返回项目列表
        </button>
      </div>
    )
  }

  return (
    <motion.div className="workspace-page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <section className="section project-topbar">
        <div className="project-headline">
          <div>
            <h2>{project.name}</h2>
            <p>
              {project.task_type === 'detection' ? '检测项目' : '分割项目'} / {project.workflow_key} / {project.task_family}
            </p>
          </div>
          <div className="topbar-actions">
            <button
              disabled={busy}
              onClick={async () => {
                try {
                  setBusy(true)
                  const task = await api.startAnnotationTask(project.id, { only_pending: true })
                  setTaskId(task.task_id)
                  pushToast(`已提交自动标注任务，共 ${task.total} 张`, 'success')
                } catch (error) {
                  pushToast(error instanceof Error ? error.message : '提交失败', 'danger')
                } finally {
                  setBusy(false)
                }
              }}
              type="button"
            >
              标注待处理图片
            </button>
            <button
              onClick={async () => {
                try {
                  await api.deleteProject(project.id)
                  await reloadProjects()
                  navigate('/projects')
                  pushToast('项目已删除', 'success')
                } catch (error) {
                  pushToast(error instanceof Error ? error.message : '删除失败', 'danger')
                }
              }}
              type="button"
            >
              删除项目
            </button>
          </div>
        </div>
        <div className="tabbar">
          {[
            ['annotate', '标注'],
            ['evaluate', '评估'],
            ['finetune', '微调'],
            ['settings', '项目设置'],
          ].map(([key, label]) => (
            <button
              className={clsx(tab === key && 'is-active')}
              key={key}
              onClick={() => setTab(key as WorkspaceTab)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <TaskTicker
          onFinished={async () => {
            await loadProject()
            await loadAnnotations(selectedImageId)
          }}
          taskId={taskId}
          title="任务进度"
        />
      </section>

      {tab === 'annotate' ? (
        <section className="project-grid">
          <aside className="section image-rail">
            <div className="section-head">
              <h2>图片</h2>
              <span>{images.length}</span>
            </div>
            <div className="toolbar rail-toolbar">
              <label className="upload-btn">
                上传图片
                <input
                  hidden
                  multiple
                  onChange={async (event) => {
                    const files = Array.from(event.target.files ?? [])
                    if (!files.length) return
                    try {
                      await api.uploadImages(project.id, files)
                      pushToast(`已上传 ${files.length} 张图片`, 'success')
                      await loadProject()
                    } catch (error) {
                      pushToast(error instanceof Error ? error.message : '上传失败', 'danger')
                    }
                    event.target.value = ''
                  }}
                  type="file"
                />
              </label>
              <label className="upload-btn secondary">
                导入数据集
                <input
                  hidden
                  onChange={async (event) => {
                    const file = event.target.files?.[0]
                    if (!file) return
                    try {
                      const format = file.name.endsWith('.json') ? 'coco' : 'yolo'
                      const result = await api.importDataset(project.id, format, file)
                      pushToast(`已导入 ${result.imported_count} 条记录`, 'success')
                      await loadProject()
                    } catch (error) {
                      pushToast(error instanceof Error ? error.message : '导入失败', 'danger')
                    }
                    event.target.value = ''
                  }}
                  type="file"
                />
              </label>
              <button
                onClick={async () => {
                  try {
                    const blob = await api.exportDataset(project.id, 'yolo')
                    downloadBlob(blob, `${project.name}-yolo.zip`)
                  } catch (error) {
                    pushToast(error instanceof Error ? error.message : '导出失败', 'danger')
                  }
                }}
                type="button"
              >
                导出 YOLO
              </button>
            </div>
            <div className="image-list">
              {images.map((image) => (
                <button
                  className={clsx('image-row', selectedImageId === image.id && 'is-active')}
                  key={image.id}
                  onClick={() => setSelectedImageId(image.id)}
                  type="button"
                >
                  <div>
                    <strong>{image.filename}</strong>
                    <span>
                      {image.width ?? '--'} × {image.height ?? '--'}
                    </span>
                  </div>
                  <div className="image-row-meta">
                    <select
                      onChange={async (event) => {
                        event.stopPropagation()
                        await api.patchImage(image.id, event.target.value as 'train' | 'val' | 'test')
                        await loadProject()
                      }}
                      value={image.split}
                    >
                      <option value="train">train</option>
                      <option value="val">val</option>
                      <option value="test">test</option>
                    </select>
                    <span className={`status-pill status-${image.status}`}>{image.status}</span>
                  </div>
                </button>
              ))}
            </div>
          </aside>

          <div className="section stage-section">
            <div className="section-head">
              <h2>标注工作区</h2>
              <span>{selectedImage?.filename ?? '未选择图片'}</span>
            </div>
            <div className="toolbar">
              <button className={drawEnabled ? 'is-active' : ''} onClick={() => setDrawEnabled(!drawEnabled)} type="button">
                框选模式
              </button>
              <button
                className={pointMode === 1 ? 'is-active' : ''}
                disabled={!settings?.workflow.supports_point_refine}
                onClick={() => setPointMode(pointMode === 1 ? null : 1)}
                type="button"
              >
                正点
              </button>
              <button
                className={pointMode === 0 ? 'is-active' : ''}
                disabled={!settings?.workflow.supports_point_refine}
                onClick={() => setPointMode(pointMode === 0 ? null : 0)}
                type="button"
              >
                负点
              </button>
              <button onClick={() => setDraftBox(null)} type="button">
                清空框
              </button>
              <button onClick={() => setDraftPoints([])} type="button">
                清空点
              </button>
            </div>
            <ImageStage
              annotations={annotations}
              draftBox={draftBox}
              draftPoints={draftPoints}
              drawEnabled={drawEnabled}
              image={selectedImage}
              onDraftBoxChange={setDraftBox}
              onPointAppend={(point) => setDraftPoints((current) => [...current, point])}
              onSelectAnnotation={setSelectedAnnotationId}
              pointMode={pointMode}
              selectedAnnotationId={selectedAnnotationId}
            />
          </div>

          <aside className="section inspector">
            <div className="section-head">
              <h2>当前操作</h2>
              <span>{selectedAnnotation ? `标注 #${selectedAnnotation.id}` : '新建标注'}</span>
            </div>
            <div className="form-grid">
              <label className="field">
                <span>标签</span>
                <select onChange={(event) => setLabelDraft(event.target.value)} value={labelDraft}>
                  {settings?.labels.map((label) => (
                    <option key={label} value={label}>
                      {label}
                    </option>
                  ))}
                  {settings?.labels.length ? null : <option value="">请先配置标签</option>}
                </select>
              </label>
            </div>
            <div className="toolbar vertical">
              <button
                className="primary-btn"
                disabled={!selectedImage || !draftBox || !labelDraft}
                onClick={async () => {
                  if (!selectedImage || !draftBox || !labelDraft) return
                  try {
                    await api.predictAnnotation(selectedImage.id, {
                      annotation_id: selectedAnnotationId,
                      label: labelDraft,
                      bbox: draftBox,
                      points: null,
                    })
                    setDraftBox(null)
                    await loadAnnotations(selectedImage.id)
                    await loadProject()
                    pushToast('框选结果已提交', 'success')
                  } catch (error) {
                    pushToast(error instanceof Error ? error.message : '提交失败', 'danger')
                  }
                }}
                type="button"
              >
                提交框选
              </button>
              <button
                disabled={!selectedImage || !selectedAnnotationId || draftPoints.length === 0 || !settings?.workflow.supports_point_refine}
                onClick={async () => {
                  if (!selectedImage || !selectedAnnotationId || draftPoints.length === 0) return
                  try {
                    await api.predictAnnotation(selectedImage.id, {
                      annotation_id: selectedAnnotationId,
                      bbox: null,
                      points: draftPoints,
                    })
                    setDraftPoints([])
                    await loadAnnotations(selectedImage.id)
                    pushToast('点修正已完成', 'success')
                  } catch (error) {
                    pushToast(error instanceof Error ? error.message : '点修正失败', 'danger')
                  }
                }}
                type="button"
              >
                应用点修正
              </button>
              <button
                disabled={!selectedAnnotationId}
                onClick={async () => {
                  if (!selectedAnnotationId || !selectedImage) return
                  try {
                    await api.confirmAnnotation(selectedAnnotationId)
                    await loadAnnotations(selectedImage.id)
                    await loadProject()
                    pushToast('标注已确认', 'success')
                  } catch (error) {
                    pushToast(error instanceof Error ? error.message : '确认失败', 'danger')
                  }
                }}
                type="button"
              >
                确认标注
              </button>
              <button
                disabled={!selectedAnnotationId}
                onClick={async () => {
                  if (!selectedAnnotationId || !selectedImage) return
                  try {
                    await api.deleteAnnotation(selectedAnnotationId)
                    await loadAnnotations(selectedImage.id)
                    await loadProject()
                    pushToast('标注已删除', 'success')
                  } catch (error) {
                    pushToast(error instanceof Error ? error.message : '删除失败', 'danger')
                  }
                }}
                type="button"
              >
                删除标注
              </button>
            </div>
            <div className="annotation-list">
              {annotations.map((annotation) => (
                <button
                  className={clsx('annotation-row', selectedAnnotationId === annotation.id && 'is-active')}
                  key={annotation.id}
                  onClick={() => {
                    setSelectedAnnotationId(annotation.id)
                    setLabelDraft(annotation.label)
                  }}
                  type="button"
                >
                  <strong>{annotation.label}</strong>
                  <span>
                    {annotation.source} / {annotation.is_confirmed ? '已确认' : '未确认'}
                  </span>
                  <span>质量 {formatPercent(annotation.quality_score)}</span>
                </button>
              ))}
            </div>
          </aside>
        </section>
      ) : null}

      {tab === 'evaluate' ? (
        <section className="section stack-section">
          <div className="section-head">
            <h2>评估</h2>
            <span>真实接口：运行、报告、对比</span>
          </div>
          <div className="toolbar">
            <button
              className="primary-btn"
              onClick={async () => {
                if (!settings) return
                try {
                  const result = await api.startEvaluation(project.id, {
                    split: settings.evaluation.split,
                    model_tag: settings.active_model_tag,
                    iou_threshold: settings.evaluation.iou_threshold,
                    max_samples: settings.evaluation.max_samples,
                  })
                  setTaskId(result.task_id)
                  pushToast(`评估任务已提交 #${result.run_id}`, 'success')
                  await loadProject()
                } catch (error) {
                  pushToast(error instanceof Error ? error.message : '评估启动失败', 'danger')
                }
              }}
              type="button"
            >
              启动评估
            </button>
          </div>
          <div className="split-layout">
            <div className="data-table">
              <div className="table-head">
                <span>Run</span>
                <span>模型</span>
                <span>状态</span>
                <span>时间</span>
                <span>F1</span>
              </div>
              <div className="table-body">
                {evaluations.map((run) => (
                  <button
                    className={clsx('table-row table-row-button', selectedRunId === run.id && 'is-active')}
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    type="button"
                  >
                    <span>#{run.id}</span>
                    <span>{run.model_tag}</span>
                    <span>{run.status}</span>
                    <span>{formatTime(run.created_at)}</span>
                    <span>{formatPercent(run.metrics?.f1)}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="detail-stack">
              {report ? (
                <>
                  <div className="metric-grid">
                    <div>
                      <span>Precision</span>
                      <strong>{formatPercent(report.metrics.precision)}</strong>
                    </div>
                    <div>
                      <span>Recall</span>
                      <strong>{formatPercent(report.metrics.recall)}</strong>
                    </div>
                    <div>
                      <span>F1</span>
                      <strong>{formatPercent(report.metrics.f1)}</strong>
                    </div>
                    <div>
                      <span>mIoU bbox</span>
                      <strong>{formatPercent(report.metrics.miou_bbox)}</strong>
                    </div>
                  </div>
                  <div className="detail-table">
                    <h3>失败样本</h3>
                    {report.summary.failure_samples.slice(0, 8).map((sample) => (
                      <div className="detail-row" key={sample.image_id}>
                        <strong>{sample.filename}</strong>
                        <span>错误 {sample.error_count}</span>
                        <span>F1 {formatPercent(sample.f1)}</span>
                        <span>耗时 {formatNumber(sample.inference_total_ms, 0)} ms</span>
                      </div>
                    ))}
                  </div>
                  {compare ? (
                    <div className="detail-table">
                      <h3>与基线对比</h3>
                      {Object.entries(compare.delta.metrics).map(([metric, value]) => (
                        <div className="detail-row" key={metric}>
                          <strong>{metric}</strong>
                          <span>当前 {formatNumber(value.current, 4)}</span>
                          <span>基线 {formatNumber(value.baseline, 4)}</span>
                          <span className={value.delta && value.delta >= 0 ? 'delta-up' : 'delta-down'}>
                            Δ {formatNumber(value.delta, 4)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="detail-empty">选择已完成的评估运行后查看报告</div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      {tab === 'finetune' ? (
        <section className="section stack-section">
          <div className="section-head">
            <h2>微调</h2>
            <span>LoRA 训练与激活</span>
          </div>
          <div className="toolbar">
            <button
              className="primary-btn"
              onClick={async () => {
                try {
                  const result = await api.startFinetune(project.id)
                  setTaskId(result.task_id)
                  pushToast(`微调任务已提交 #${result.job_id}`, 'success')
                  await loadProject()
                } catch (error) {
                  pushToast(error instanceof Error ? error.message : '微调启动失败', 'danger')
                }
              }}
              type="button"
            >
              启动微调
            </button>
          </div>
          <div className="split-layout">
            <div className="data-table">
              <div className="table-head">
                <span>Job</span>
                <span>状态</span>
                <span>模型标记</span>
                <span>创建时间</span>
                <span>操作</span>
              </div>
              <div className="table-body">
                {finetuneJobs.map((job) => (
                  <div className="table-row" key={job.id}>
                    <span>#{job.id}</span>
                    <span>{job.status}</span>
                    <span>{job.model_tag}</span>
                    <span>{formatTime(job.created_at)}</span>
                    <span className="row-actions">
                      <button
                        onClick={async () => {
                          try {
                            const result = await api.getFinetuneLog(job.id)
                            setSelectedJobLog(result.log)
                          } catch (error) {
                            pushToast(error instanceof Error ? error.message : '日志读取失败', 'danger')
                          }
                        }}
                        type="button"
                      >
                        日志
                      </button>
                      <button
                        disabled={job.status !== 'done'}
                        onClick={async () => {
                          try {
                            const result = await api.activateFinetune(job.id)
                            pushToast(result.message, 'success')
                            await loadProject()
                          } catch (error) {
                            pushToast(error instanceof Error ? error.message : '激活失败', 'danger')
                          }
                        }}
                        type="button"
                      >
                        激活
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div className="detail-stack">
              <div className="metric-grid">
                <div>
                  <span>活动模型</span>
                  <strong>{settings?.active_model_tag ?? '--'}</strong>
                </div>
                <div>
                  <span>已完成任务</span>
                  <strong>{finetuneJobs.filter((job) => job.status === 'done').length}</strong>
                </div>
                <div>
                  <span>运行中任务</span>
                  <strong>{finetuneJobs.filter((job) => job.status === 'running').length}</strong>
                </div>
                <div>
                  <span>最近时间</span>
                  <strong>{formatTime(finetuneJobs[0]?.created_at)}</strong>
                </div>
              </div>
              <pre className="log-panel">{selectedJobLog || '选择日志后在此查看训练输出'}</pre>
            </div>
          </div>
        </section>
      ) : null}

      {tab === 'settings' ? (
        <section className="section stack-section">
          <div className="section-head">
            <h2>项目设置</h2>
            <span>仅提交 labels 与 workflow_key</span>
          </div>
          <div className="form-grid three-col">
            <label className="field full-span">
              <span>标签列表</span>
              <textarea onChange={(event) => setLabelText(event.target.value)} rows={6} value={labelText} />
            </label>
            <label className="field">
              <span>工作流</span>
              <select
                onChange={(event) =>
                  settings ? setSettings({ ...settings, workflow_key: event.target.value }) : undefined
                }
                value={settings?.workflow_key ?? ''}
              >
                {settings?._meta.available_workflows
                  .filter((workflow) => workflow.task_type === project.task_type)
                  .map((workflow) => (
                    <option key={workflow.key} value={workflow.key}>
                      {workflow.display_name} / {workflow.key}
                    </option>
                  ))}
              </select>
            </label>
            <label className="field">
              <span>当前模型</span>
              <input readOnly value={settings?.active_model_tag ?? ''} />
            </label>
            <label className="field">
              <span>切换模型</span>
              <select
                onChange={async (event) => {
                  if (!settings) return
                  try {
                    const result = await api.activateProjectModel(project.id, event.target.value)
                    setSettings(result.settings)
                    pushToast(result.activation.message, 'success')
                    await loadProject()
                  } catch (error) {
                    pushToast(error instanceof Error ? error.message : '切换失败', 'danger')
                  }
                }}
                value={settings?.active_model_tag ?? 'base'}
              >
                <option value="base">base</option>
                {finetuneJobs
                  .filter((job) => job.status === 'done')
                  .map((job) => (
                    <option key={job.model_tag} value={job.model_tag}>
                      {job.model_tag}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <div className="toolbar">
            <button
              className="primary-btn"
              onClick={async () => {
                if (!settings) return
                try {
                  const result = await api.patchProjectSettings(project.id, {
                    labels: toLabelList(labelText),
                    workflow_key: settings.workflow_key,
                  })
                  setSettings(result.settings)
                  setLabelText(result.settings.labels.join('\n'))
                  pushToast(result.change.message, 'success')
                  await loadProject()
                } catch (error) {
                  pushToast(error instanceof Error ? error.message : '保存失败', 'danger')
                }
              }}
              type="button"
            >
              保存项目设置
            </button>
          </div>
          <div className="kv-grid">
            <div>
              <span>系统档位</span>
              <strong>{settings?._meta.active_system_profile ?? '--'}</strong>
            </div>
            <div>
              <span>项目解析档位</span>
              <strong>{settings?._meta.resolved_project_profile ?? '--'}</strong>
            </div>
            <div>
              <span>基础模型</span>
              <strong>{settings?.llm.base_model ?? '--'}</strong>
            </div>
            <div>
              <span>SAM 权重</span>
              <strong>{settings?.sam.checkpoint ?? '--'}</strong>
            </div>
          </div>
        </section>
      ) : null}
    </motion.div>
  )
}
