import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'

import { API_BASE_URL, api } from '../api'
import type { TaskStatusPayload } from '../types'
import { clsx, wsBaseUrl } from '../utils'

type TaskTickerProps = {
  taskId: string | null
  title: string
  onFinished?: (task: TaskStatusPayload) => void
}

const doneStates = new Set(['SUCCESS', 'FAILURE'])

export function TaskTicker({ taskId, title, onFinished }: TaskTickerProps) {
  const [task, setTask] = useState<TaskStatusPayload | null>(null)
  const [transport, setTransport] = useState<'ws' | 'poll' | null>(null)
  const onFinishedRef = useRef(onFinished)

  useEffect(() => {
    onFinishedRef.current = onFinished
  }, [onFinished])

  useEffect(() => {
    if (!taskId) {
      setTask(null)
      setTransport(null)
      return
    }

    let closed = false
    let timer: number | null = null
    let fallbackTimer: number | null = null
    let socket: WebSocket | null = null
    let wsOpened = false

    const finish = (next: TaskStatusPayload) => {
      setTask(next)
      if (doneStates.has(next.status)) {
        onFinishedRef.current?.(next)
      }
    }

    const fetchSnapshot = async () => {
      const next = await api.getTaskStatus(taskId)
      if (closed) return
      finish(next)
    }

    const poll = async () => {
      try {
        const next = await api.getTaskStatus(taskId)
        if (closed) return
        setTransport('poll')
        finish(next)
        if (!doneStates.has(next.status)) {
          timer = window.setTimeout(poll, 2000)
        }
      } catch {
        if (!closed) timer = window.setTimeout(poll, 3000)
      }
    }

    try {
      socket = new WebSocket(`${wsBaseUrl(API_BASE_URL)}/ws/tasks/${taskId}`)
      socket.onopen = () => {
        if (!closed) {
          wsOpened = true
          if (fallbackTimer) {
            window.clearTimeout(fallbackTimer)
            fallbackTimer = null
          }
          setTransport('ws')
        }
      }
      socket.onmessage = (event) => {
        const next = JSON.parse(event.data) as {
          task_id: string
          status: TaskStatusPayload['status']
          progress: number
          message: string | null
        }
        setTask((current) => {
          const merged = {
            task_id: next.task_id,
            kind: current?.kind ?? '',
            queue: current?.queue ?? '',
            status: next.status,
            progress: next.progress,
            message: next.message,
            version: current?.version ?? 0,
          }
          if (doneStates.has(merged.status)) {
            onFinishedRef.current?.(merged)
          }
          return merged
        })
      }
      socket.onerror = () => {
        socket?.close()
      }
      socket.onclose = () => {
        if (!closed && !wsOpened) {
          poll()
        }
      }
    } catch {
      poll()
    }

    void fetchSnapshot().catch(() => {})
    fallbackTimer = window.setTimeout(() => {
      if (!closed && !wsOpened) {
        poll()
      }
    }, 1500)

    return () => {
      closed = true
      if (timer) window.clearTimeout(timer)
      if (fallbackTimer) window.clearTimeout(fallbackTimer)
      socket?.close()
    }
  }, [taskId])

  const tone = useMemo(() => {
    if (!task) return 'neutral'
    if (task.status === 'FAILURE') return 'danger'
    if (task.status === 'SUCCESS') return 'success'
    return 'primary'
  }, [task])

  return (
    <AnimatePresence>
      {taskId && task ? (
        <motion.div
          className={clsx('task-ticker', `tone-${tone}`)}
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.24, ease: 'easeOut' }}
        >
          <div className="task-ticker-head">
            <strong>{title}</strong>
            <span>{transport === 'ws' ? 'WebSocket' : '轮询'}</span>
          </div>
          <div className="task-ticker-main">
            <span>{task.status}</span>
            <span>{task.message ?? '处理中'}</span>
            <span>{task.progress}%</span>
          </div>
          <div className="task-progress">
            <i style={{ width: `${Math.max(4, task.progress)}%` }} />
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
