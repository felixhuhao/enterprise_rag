import { computed, onUnmounted, ref, watch } from 'vue'

interface AutoFitColumnConfig {
  width: number
  minWidth?: number
  maxWidth?: number
  flex?: boolean
}

interface AutoFitOptions {
  minWidth?: number
}

type ColumnConfigs = Record<string, AutoFitColumnConfig>
type ColumnWidths = Record<string, number>

export function useAutoFitColumns(
  storageKey: string,
  columns: ColumnConfigs,
  options: AutoFitOptions = {},
) {
  const baseMinWidth = options.minWidth ?? 44
  const containerRef = ref<HTMLElement | null>(null)
  const containerWidth = ref(0)
  const manualWidths = ref<ColumnWidths>(loadManualWidths(storageKey, columns))
  let resizeObserver: ResizeObserver | null = null

  const widths = computed(() => fitWidths(
    columns,
    manualWidths.value,
    containerWidth.value,
    baseMinWidth,
  ))

  function columnWidth(key: string): number | undefined {
    return widths.value[key]
  }

  function columnStyle(key: string): { width?: string } {
    const width = columnWidth(key)
    return width ? { width: `${width}px` } : {}
  }

  function setColumnWidth(key: string, width: number) {
    if (!(key in columns)) return
    const minWidth = columnMinWidth(columns[key], baseMinWidth)
    manualWidths.value = {
      ...manualWidths.value,
      [key]: normalizeWidth(width, minWidth, columns[key].maxWidth),
    }
    persistManualWidths(storageKey, manualWidths.value)
  }

  function onColumnResize(dataIndex: string | number, width: number) {
    setColumnWidth(String(dataIndex), width)
  }

  function startResize(key: string, event: MouseEvent) {
    if (!(key in columns)) return
    event.preventDefault()
    event.stopPropagation()

    const startX = event.clientX
    const startWidth = columnWidth(key) ?? columns[key].width

    const onMove = (moveEvent: MouseEvent) => {
      setColumnWidth(key, startWidth + moveEvent.clientX - startX)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('contextmenu', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('contextmenu', onUp)
  }

  function resetColumnWidths() {
    manualWidths.value = {}
    try {
      window.localStorage.removeItem(storageKey)
    } catch {
      // ignore storage failures
    }
  }

  const stopWatch = watch(containerRef, (element) => {
    resizeObserver?.disconnect()
    resizeObserver = null
    if (!element) {
      containerWidth.value = 0
      return
    }
    containerWidth.value = element.clientWidth
    resizeObserver = new ResizeObserver(([entry]) => {
      containerWidth.value = Math.floor(entry.contentRect.width)
    })
    resizeObserver.observe(element)
  }, { flush: 'post' })

  onUnmounted(() => {
    stopWatch()
    resizeObserver?.disconnect()
    resizeObserver = null
  })

  return {
    columnStyle,
    columnWidth,
    containerRef,
    onColumnResize,
    resetColumnWidths,
    startResize,
    widths,
  }
}

function fitWidths(
  columns: ColumnConfigs,
  manualWidths: ColumnWidths,
  containerWidth: number,
  baseMinWidth: number,
): ColumnWidths {
  const keys = Object.keys(columns)
  const widths = Object.fromEntries(keys.map((key) => [
    key,
    normalizeWidth(manualWidths[key] ?? columns[key].width, columnMinWidth(columns[key], baseMinWidth), columns[key].maxWidth),
  ])) as ColumnWidths
  const targetWidth = Math.max(0, Math.floor(containerWidth) - 2)

  if (!targetWidth) return roundWidths(widths)

  shrinkToFit(keys, columns, widths, targetWidth, baseMinWidth)
  growFlexToFill(keys, columns, widths, targetWidth)

  return roundWidths(widths)
}

function shrinkToFit(
  keys: string[],
  columns: ColumnConfigs,
  widths: ColumnWidths,
  targetWidth: number,
  baseMinWidth: number,
) {
  let overflow = totalWidth(widths) - targetWidth
  while (overflow > 0.5) {
    const candidates = keys.filter((key) => widths[key] > columnMinWidth(columns[key], baseMinWidth))
    if (!candidates.length) return

    const capacity = candidates.reduce(
      (sum, key) => sum + widths[key] - columnMinWidth(columns[key], baseMinWidth),
      0,
    )
    if (capacity <= 0) return

    for (const key of candidates) {
      const minWidth = columnMinWidth(columns[key], baseMinWidth)
      const reduction = overflow * ((widths[key] - minWidth) / capacity)
      widths[key] = Math.max(minWidth, widths[key] - reduction)
    }
    overflow = totalWidth(widths) - targetWidth
  }
}

function growFlexToFill(
  keys: string[],
  columns: ColumnConfigs,
  widths: ColumnWidths,
  targetWidth: number,
) {
  let extra = targetWidth - totalWidth(widths)
  if (extra <= 0.5) return

  while (extra > 0.5) {
    const candidates = keys.filter((key) => columns[key].flex && (
      columns[key].maxWidth === undefined || widths[key] < columns[key].maxWidth!
    ))
    if (!candidates.length) return

    const perColumn = extra / candidates.length
    let consumed = 0
    for (const key of candidates) {
      const maxWidth = columns[key].maxWidth ?? Number.POSITIVE_INFINITY
      const nextWidth = Math.min(maxWidth, widths[key] + perColumn)
      consumed += nextWidth - widths[key]
      widths[key] = nextWidth
    }
    if (consumed <= 0.5) return
    extra = targetWidth - totalWidth(widths)
  }
}

function totalWidth(widths: ColumnWidths): number {
  return Object.values(widths).reduce((sum, width) => sum + width, 0)
}

function roundWidths(widths: ColumnWidths): ColumnWidths {
  return Object.fromEntries(
    Object.entries(widths).map(([key, width]) => [key, Math.max(1, Math.round(width))]),
  )
}

function columnMinWidth(column: AutoFitColumnConfig, baseMinWidth: number): number {
  return column.minWidth ?? baseMinWidth
}

function normalizeWidth(width: number, minWidth: number, maxWidth?: number): number {
  const bounded = maxWidth === undefined ? width : Math.min(width, maxWidth)
  return Math.max(minWidth, Math.round(bounded))
}

function loadManualWidths(storageKey: string, columns: ColumnConfigs): ColumnWidths {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return Object.fromEntries(
      Object.keys(columns)
        .filter((key) => typeof parsed[key] === 'number')
        .map((key) => [key, parsed[key] as number]),
    )
  } catch {
    return {}
  }
}

function persistManualWidths(storageKey: string, widths: ColumnWidths) {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(widths))
  } catch {
    // ignore storage failures
  }
}
