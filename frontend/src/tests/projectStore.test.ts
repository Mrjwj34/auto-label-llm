import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockBackend } from '../backend/mockBackend'
import { useProjectStore } from '../stores/projectStore'

describe('projectStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetMockBackend()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads project list from mock backend', async () => {
    const store = useProjectStore()
    const pending = store.loadProjects()
    await vi.advanceTimersByTimeAsync(100)
    await pending

    expect(store.projects.length).toBeGreaterThan(0)
    expect(store.workflows.some((workflow) => workflow.key === 'generic_instance_segmentation')).toBe(true)
  })

  it('creates a project without real backend', async () => {
    const store = useProjectStore()
    const load = store.loadProjects()
    await vi.advanceTimersByTimeAsync(100)
    await load

    store.openCreateDrawer('generic_detection')
    store.createDraft.name = 'Mock Project'
    store.createDraft.labels = ['crack', 'patch']

    const create = store.createProject()
    await vi.runAllTimersAsync()
    const created = await create
    expect(created).not.toBeNull()
    expect(created?.name).toBe('Mock Project')
    expect(created?.workflowKey).toBe('generic_detection')
    expect(created?.taskType).toBe('detection')
    expect(store.projects[0]?.name).toBe('Mock Project')
    expect(store.settings?.labels).toEqual(['crack', 'patch'])
  })
})
