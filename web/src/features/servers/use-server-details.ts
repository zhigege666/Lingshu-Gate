import { useCallback, useEffect, useRef, useState } from "react"
import { api, type McpServerDetailSection, type McpServerDetailSlice, type ToolClassification } from "@/api/client"

export type DetailSection = McpServerDetailSection | "diagnostics"
export type DetailState = {
  loading: boolean
  data?: McpServerDetailSlice
  error?: string
  classifications?: ToolClassification[]
  classificationError?: string
}

export function useServerDetails(serverId: string | null, refreshKey: unknown, canReadClassifications: boolean) {
  const [states, setStates] = useState<Partial<Record<DetailSection, DetailState>>>({})
  const cache = useRef<Partial<Record<DetailSection, DetailState>>>({})
  const controllers = useRef(new Map<DetailSection, AbortController>())
  const owner = useRef({ serverId, refreshKey, canReadClassifications })
  const generation = useRef(0)

  useEffect(() => {
    generation.current += 1
    controllers.current.forEach(controller => controller.abort())
    controllers.current.clear()
    cache.current = {}
    owner.current = { serverId, refreshKey, canReadClassifications }
    setStates({})
    return () => {
      generation.current += 1
      controllers.current.forEach(controller => controller.abort())
      controllers.current.clear()
    }
  }, [serverId, refreshKey, canReadClassifications])

  const load = useCallback(async (section: DetailSection, force = false) => {
    if (!serverId) return
    if (!force && (cache.current[section]?.loading || cache.current[section]?.data)) return
    controllers.current.get(section)?.abort()
    const controller = new AbortController()
    controllers.current.set(section, controller)
    const currentGeneration = generation.current
    function publish(state: DetailState) {
      if (controller.signal.aborted || currentGeneration !== generation.current) return
      cache.current = { ...cache.current, [section]: state }
      setStates(cache.current)
    }
    publish({ loading: true })
    try {
      // 分区只在用户打开时读取；概览的分类失败不能阻断独立的运行态摘要。
      const [detail, classifications] = await Promise.allSettled([
        api.serverDetail(serverId, {
          section: section === "diagnostics" ? undefined : section,
          limit: 40,
          signal: controller.signal,
        }),
        section === "overview" && canReadClassifications
          ? api.toolClassifications({ server_id: serverId }, controller.signal)
          : Promise.resolve(null),
      ])
      if (detail.status === "rejected") throw detail.reason
      publish({
        loading: false,
        data: detail.value,
        classifications: classifications.status === "fulfilled" ? classifications.value?.classifications : undefined,
        classificationError: classifications.status === "rejected" ? String(classifications.reason) : undefined,
      })
    } catch (error) {
      publish({ loading: false, error: error instanceof Error ? error.message : String(error) })
    } finally {
      if (controllers.current.get(section) === controller) controllers.current.delete(section)
    }
  }, [serverId, canReadClassifications])

  // React effect 执行前也隔离上一个服务的结果，避免切换服务时短暂显示旧 Schema 或日志。
  const matchesOwner = owner.current.serverId === serverId && owner.current.refreshKey === refreshKey && owner.current.canReadClassifications === canReadClassifications
  return { states: matchesOwner ? states : {}, load }
}
