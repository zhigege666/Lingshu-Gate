import { describe, expect, it, vi } from "vitest"
import { createEditorExitRegistry } from "./editor-navigation-guard"

describe("open editor navigation guards", () => {
  it("blocks a pending editor independently of whether its draft is dirty", () => {
    const registry = createEditorExitRegistry()
    const close = registry.register({ dirty: false, pending: true })
    expect(registry.getSnapshot()).toEqual({ anyDirty: false, anyPending: true })
    close()
    expect(registry.getSnapshot()).toEqual({ anyDirty: false, anyPending: false })
  })

  it("does not lose another editor's protection when one editor closes", () => {
    const registry = createEditorExitRegistry()
    const closeDirty = registry.register({ dirty: true, pending: false })
    const closePending = registry.register({ dirty: false, pending: true })
    expect(registry.getSnapshot()).toEqual({ anyDirty: true, anyPending: true })
    closeDirty()
    closeDirty()
    expect(registry.getSnapshot()).toEqual({ anyDirty: false, anyPending: true })
    closePending()
    expect(registry.getSnapshot()).toEqual({ anyDirty: false, anyPending: false })
  })

  it("cleans up changed draft registrations and keeps unchanged snapshots stable", () => {
    const registry = createEditorExitRegistry()
    const notify = vi.fn()
    const unsubscribe = registry.subscribe(notify)
    const cleanSnapshot = registry.getSnapshot()
    const closeClean = registry.register({ dirty: false, pending: false })
    expect(registry.getSnapshot()).toBe(cleanSnapshot)
    expect(notify).not.toHaveBeenCalled()
    closeClean()
    const closeDirty = registry.register({ dirty: true, pending: false })
    expect(notify).toHaveBeenCalledTimes(1)
    closeDirty()
    expect(notify).toHaveBeenCalledTimes(2)
    unsubscribe()
    registry.register({ dirty: true, pending: false })
    expect(notify).toHaveBeenCalledTimes(2)
  })

  it("captures only exit flags without retaining a mutable caller state", () => {
    const registry = createEditorExitRegistry()
    const state = { dirty: true, pending: false }
    const close = registry.register(state)
    state.dirty = false
    state.pending = true
    expect(registry.getSnapshot()).toEqual({ anyDirty: true, anyPending: false })
    close()
    expect(registry.getSnapshot()).toEqual({ anyDirty: false, anyPending: false })
  })
})
