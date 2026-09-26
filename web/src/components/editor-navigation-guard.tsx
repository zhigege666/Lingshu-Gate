import { createContext, useState, useSyncExternalStore } from "react"

export type EditorExitState = { dirty: boolean; pending: boolean }
export type RegisterEditorExit = (state: EditorExitState) => () => void
export const EditorNavigationContext = createContext<RegisterEditorExit | null>(null)

/** Keeps only exit flags, never form values or secrets. Each open editor owns a token. */
export function createEditorExitRegistry() {
  const editors = new Map<symbol, EditorExitState>()
  const listeners = new Set<() => void>()
  let snapshot = { anyDirty: false, anyPending: false }
  function publish() {
    const next = {
      anyDirty: [...editors.values()].some(editor => editor.dirty),
      anyPending: [...editors.values()].some(editor => editor.pending),
    }
    if (next.anyDirty === snapshot.anyDirty && next.anyPending === snapshot.anyPending) return
    snapshot = next
    listeners.forEach(listener => listener())
  }
  const register: RegisterEditorExit = state => {
    const token = Symbol("open-editor")
    editors.set(token, { dirty: state.dirty, pending: state.pending })
    publish()
    return () => { if (editors.delete(token)) publish() }
  }
  return {
    register,
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
  }
}

export function useEditorNavigationGuards() {
  const [registry] = useState(createEditorExitRegistry)
  const snapshot = useSyncExternalStore(registry.subscribe, registry.getSnapshot, registry.getSnapshot)
  return { providerValue: registry.register, ...snapshot }
}
