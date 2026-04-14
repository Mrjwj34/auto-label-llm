import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockBackend } from '../backend/mockBackend'
import { useDatasetStore } from '../stores/datasetStore'

describe('datasetStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetMockBackend()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads workspace from mock backend', async () => {
    const store = useDatasetStore()
    const pending = store.load(12)
    await vi.advanceTimersByTimeAsync(100)
    await pending

    expect(store.workspace?.summary.name).toBe('建筑质检批次 01')
    expect(store.workspace?.reviewQueue.length).toBeGreaterThan(0)
  })

  it('simulates batch annotate progress with mock backend', async () => {
    const store = useDatasetStore()
    const load = store.load(12)
    await vi.advanceTimersByTimeAsync(100)
    await load

    const start = store.startBatchAnnotate()
    await vi.advanceTimersByTimeAsync(200)
    await start
    expect(store.workspace?.task.status).toBe('RUNNING')

    await vi.advanceTimersByTimeAsync(8000)

    expect(store.workspace?.task.status).toBe('SUCCESS')
    expect(store.workspace?.images.some((image) => image.status === 'done')).toBe(true)
  })
})
