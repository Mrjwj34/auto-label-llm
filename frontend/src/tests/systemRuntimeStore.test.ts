import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockBackend } from '../backend/mockBackend'
import { useSystemRuntimeStore } from '../stores/systemRuntimeStore'

describe('systemRuntimeStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetMockBackend()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('activates runtime profile from mock backend', async () => {
    const store = useSystemRuntimeStore()
    const hydrate = store.hydrate()
    await vi.advanceTimersByTimeAsync(100)
    await hydrate

    const activate = store.activateProfile('demo_prod')
    await vi.advanceTimersByTimeAsync(220)
    await activate

    expect(store.runtime?.activeProfile).toBe('demo_prod')
    expect(store.runtime?.modelName).toBe('qwen3-vl-4b')
  })

  it('runs selftest from mock backend', async () => {
    const store = useSystemRuntimeStore()
    const hydrate = store.hydrate()
    await vi.advanceTimersByTimeAsync(100)
    await hydrate

    const run = store.runSelftest()
    await vi.advanceTimersByTimeAsync(300)
    await run

    expect(store.diagnostics?.selftest.every((check) => check.status === 'PASS')).toBe(true)
  })
})
