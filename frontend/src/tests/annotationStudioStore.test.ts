import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockBackend } from '../backend/mockBackend'
import { useAnnotationStudioStore } from '../stores/annotationStudioStore'

describe('annotationStudioStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetMockBackend()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('creates a manual annotation bbox', async () => {
    const store = useAnnotationStudioStore()
    const load = store.load(12, 1801)
    await vi.runAllTimersAsync()
    await load

    const originalCount = store.image?.annotations.length ?? 0
    const create = store.createAnnotation('建筑', [0.1, 0.12, 0.4, 0.45])
    await vi.runAllTimersAsync()
    await create

    expect(store.image?.annotations.length).toBe(originalCount + 1)
    expect(store.selectedAnnotation?.label).toBe('建筑')
    expect(store.selectedAnnotation?.source).toBe('manual')
    expect(store.selectedAnnotation?.bbox).toEqual([0.1, 0.12, 0.4, 0.45])
  })

  it('walks the review queue backward and forward', async () => {
    const store = useAnnotationStudioStore()
    const load = store.load(12, 1801)
    await vi.runAllTimersAsync()
    await load

    const nextImageId = store.nextImageId()
    expect(store.previousImageId()).toBeNull()
    expect(nextImageId).not.toBeNull()

    const nextLoad = store.load(12, nextImageId ?? undefined)
    await vi.runAllTimersAsync()
    await nextLoad

    expect(store.previousImageId()).toBe(1801)
  })
})
