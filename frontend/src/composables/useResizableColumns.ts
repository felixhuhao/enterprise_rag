import { ref } from 'vue'

type ColumnWidthDefaults = Record<string, number | undefined>

interface ResizableColumnOptions {
  minWidth?: number
}

export function useResizableColumns(
  storageKey: string,
  defaults: ColumnWidthDefaults,
  options: ResizableColumnOptions = {},
) {
  const minWidth = options.minWidth ?? 44
  const widths = ref<ColumnWidthDefaults>(loadWidths(storageKey, defaults))

  function columnWidth(key: string): number | undefined {
    return widths.value[key]
  }

  function onColumnResize(dataIndex: string | number, width: number) {
    setColumnWidth(String(dataIndex), width)
  }

  function setColumnWidth(key: string, width: number) {
    if (!(key in defaults)) return
    widths.value = {
      ...widths.value,
      [key]: normalizeWidth(width, minWidth),
    }
    persistWidths(storageKey, widths.value)
  }

  function startResize(key: string, event: MouseEvent) {
    if (!(key in defaults)) return
    event.preventDefault()
    event.stopPropagation()

    const startX = event.clientX
    const startWidth = columnWidth(key) ?? defaults[key] ?? minWidth

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
    widths.value = { ...defaults }
    try {
      window.localStorage.removeItem(storageKey)
    } catch {
      // ignore storage failures
    }
  }

  return {
    columnWidth,
    onColumnResize,
    resetColumnWidths,
    startResize,
    widths,
  }
}

function loadWidths(storageKey: string, defaults: ColumnWidthDefaults): ColumnWidthDefaults {
  if (typeof window === 'undefined') return { ...defaults }
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return { ...defaults }
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return Object.fromEntries(
      Object.entries(defaults).map(([key, defaultWidth]) => [
        key,
        typeof parsed[key] === 'number' ? (parsed[key] as number) : defaultWidth,
      ]),
    )
  } catch {
    return { ...defaults }
  }
}

function persistWidths(storageKey: string, widths: ColumnWidthDefaults) {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(widths))
  } catch {
    // ignore storage failures
  }
}

function normalizeWidth(width: number, minWidth: number) {
  return Math.max(minWidth, Math.round(width))
}
