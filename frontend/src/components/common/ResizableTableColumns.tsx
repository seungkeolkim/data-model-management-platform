/**
 * Ant Design Table에 드래그 리사이즈 가능한 컬럼을 붙이기 위한 공용 유틸.
 *
 * 제공:
 * - ResizableHeaderCell: 우측 경계에 6px 드래그 손잡이를 가진 <th> 대체 컴포넌트
 * - useResizableColumnWidths: 초기 컬럼 배열을 받아 width를 state로 관리하고,
 *   Table에 꽂을 columns / components를 반환하는 훅
 *
 * 외부 리사이즈 패키지(react-resizable 등) 없이 마우스 이벤트로만 동작한다.
 * 새로고침 시 너비는 초기값으로 되돌아간다(로컬스토리지 저장은 필요 시 별도 추가).
 */
import { useCallback, useRef, useState } from 'react'
import type { CSSProperties, ReactNode, ThHTMLAttributes } from 'react'

/**
 * 컬럼 최소 너비(px). 음수 방지 외 사용자 의도된 폭 조정을 막지 않는다.
 * 0 이면 사실상 floor 없음 — 손잡이 자체가 절대 위치라 0 에서도 다시 잡아 늘릴 수 있다.
 */
const MINIMUM_COLUMN_WIDTH_PX = 0

interface ResizableHeaderCellProps extends ThHTMLAttributes<HTMLTableCellElement> {
  /** 현재 너비. 미지정이면 리사이즈 비활성화(일반 th처럼 동작). */
  resizeWidth?: number
  /** 드래그 중 호출. 최종 너비를 인자로 받는다. */
  onResize?: (nextWidth: number) => void
  children?: ReactNode
}

/**
 * 드래그 손잡이가 붙은 <th>. Ant Table `components.header.cell`로 주입.
 * onResize가 없으면 일반 th처럼 그대로 렌더.
 */
export function ResizableHeaderCell({
  resizeWidth,
  onResize,
  children,
  style,
  ...restThProps
}: ResizableHeaderCellProps) {
  const dragStartClientXRef = useRef(0)
  const dragStartWidthRef = useRef(0)

  const handleMouseDown = useCallback(
    (event: React.MouseEvent<HTMLSpanElement>) => {
      if (!onResize || resizeWidth == null) return
      event.preventDefault()
      event.stopPropagation()
      dragStartClientXRef.current = event.clientX
      dragStartWidthRef.current = resizeWidth

      // 드래그 동안은 React state 갱신 없이 DOM 직접 조작.
      // table-layout: fixed 에서는 `<colgroup>` 의 `<col>` 이 컬럼 너비의 SSOT.
      // mouseup 시점에 onResize(lastWidth) 1회 호출로 React state 와 DOM 을 일치.
      //
      // 중요: AntD v5 가 `scroll: { x }` 를 받으면 같은 `.ant-table-container` 안에
      // 헤더 `<table>` 과 바디 `<table>` 을 별개로 그리고 각자 `<colgroup>` 을
      // 갖는다. 두 colgroup 의 같은 cellIndex col 을 동시에 갱신.
      //
      // 또한 페이지 CSS 가 inner table 에 `width: max-content` 를 강제 — 매 mousemove
      // 마다 브라우저가 모든 col 합을 다시 계산해야 함. 줄이기/늘리기 비대칭 (줄일 때
      // 후행 컬럼이 viewport 안으로 끌려와 repaint 면적이 큼) 과 합쳐져 셔링크가
      // 무거워짐. 두 가지 완화:
      //   (1) rAF 로 mousemove → DOM 갱신 횟수를 최대 60fps 로 제한 (이상치 mouse rate
      //       와 reflow 누적 방지).
      //   (2) 드래그 동안은 table 의 width 를 직접 px 로 박아 max-content 동적 계산 회피.
      const handleSpan = event.currentTarget
      const thEl = handleSpan.parentElement as HTMLTableCellElement | null
      const cellIndex = thEl ? thEl.cellIndex : -1
      const containerEl =
        thEl?.closest('.ant-table-container') as HTMLElement | null

      // 같은 container 안의 모든 (헤더 / 바디) table + colgroup 수집.
      const tableInfos: Array<{
        tableEl: HTMLTableElement
        colEls: HTMLElement[]
      }> = []
      if (cellIndex >= 0) {
        const root: ParentNode | null =
          containerEl ?? thEl?.closest('table') ?? null
        if (root) {
          const tables = Array.from(
            root.querySelectorAll('table'),
          ) as HTMLTableElement[]
          for (const tableEl of tables) {
            const colgroup = tableEl.querySelector('colgroup')
            if (!colgroup) continue
            const colEls = Array.from(colgroup.children) as HTMLElement[]
            tableInfos.push({ tableEl, colEls })
          }
        }
      }

      // 드래그 시작 시점에 모든 col 의 현재 폭을 측정 (px). 이후 dragged column 만
      // delta 적용. 매 frame 합을 즉시 산출해 table.style.width 에 박는다.
      const initialColWidthsPerTable: number[][] = tableInfos.map(({ colEls }) =>
        colEls.map((c) => {
          const styled = parseFloat(c.style.width || '')
          if (!Number.isNaN(styled) && styled > 0) return styled
          // colgroup col 에 inline width 가 없으면 실제 렌더 폭을 측정.
          return c.getBoundingClientRect().width
        }),
      )

      // 드래그 실제 발생 여부 + 마지막으로 적용한 폭. mouseup 에서 사용.
      let didActuallyDrag = false
      let lastNextWidth = dragStartWidthRef.current

      // rAF 스케줄러 — 다중 mousemove 를 한 frame 으로 coalesce.
      let pendingClientX = event.clientX
      let rafId: number | null = null

      const flushPending = () => {
        rafId = null
        const deltaPx = pendingClientX - dragStartClientXRef.current
        if (deltaPx !== 0) didActuallyDrag = true
        const nextWidth = Math.max(
          MINIMUM_COLUMN_WIDTH_PX,
          dragStartWidthRef.current + deltaPx,
        )
        lastNextWidth = nextWidth
        const widthPx = `${nextWidth}px`

        // 각 (헤더 / 바디) table 의 cellIndex col 갱신 + table 자체의 폭을
        // 합으로 직접 박아 max-content 재계산 회피.
        for (let i = 0; i < tableInfos.length; i++) {
          const { tableEl, colEls } = tableInfos[i]
          const target = colEls[cellIndex]
          if (target) target.style.width = widthPx
          const initial = initialColWidthsPerTable[i]
          let sum = 0
          for (let j = 0; j < initial.length; j++) {
            sum += j === cellIndex ? nextWidth : initial[j]
          }
          tableEl.style.width = `${sum}px`
        }
        if (thEl) thEl.style.width = widthPx
      }

      const handleMouseMove = (moveEvent: MouseEvent) => {
        pendingClientX = moveEvent.clientX
        if (rafId !== null) return
        rafId = window.requestAnimationFrame(flushPending)
      }
      const handleMouseUp = () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
        // 보류 중인 frame 이 있으면 즉시 한 번 더 flush 해 최종 폭 반영.
        if (rafId !== null) {
          window.cancelAnimationFrame(rafId)
          flushPending()
        }
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        // 인라인 table.style.width 는 React state 동기화 후 자동으로 무시되므로
        // 굳이 비울 필요 없음 (다음 render 에서 width 가 제거되거나 재설정됨).
        // 단, max-content 재계산이 필요한 페이지를 위해 명시적으로 제거.
        for (const { tableEl } of tableInfos) {
          tableEl.style.width = ''
        }
        // 최종 폭을 React state 에 1회 동기화. 안 하면 다음 re-render 때 DOM 이 원복된다.
        onResize(lastNextWidth)

        // 드래그 종료 직후 브라우저는 mousedown 시점과 mouseup 시점의 공통 조상 위에서
        // click 이벤트를 한 번 발생시킨다. 핸들을 가로로 끌면 mouseup 이 부모 `<th>` 에서
        // 일어나기 쉽고, AntD Table 의 정렬 핸들러가 그 click 을 받아 정렬이 토글된다.
        // → 드래그가 실제로 일어난 경우에만 capture 단계에서 다음 click 을 1회 차단.
        if (!didActuallyDrag) return
        const swallowClick = (clickEvent: MouseEvent) => {
          clickEvent.preventDefault()
          clickEvent.stopPropagation()
          window.removeEventListener('click', swallowClick, true)
        }
        window.addEventListener('click', swallowClick, true)
        // safety: click 이 영영 안 올 수도 있으니 짧은 시간 뒤 자동 제거.
        window.setTimeout(() => {
          window.removeEventListener('click', swallowClick, true)
        }, 100)
      }

      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
    },
    [onResize, resizeWidth],
  )

  // onResize/width가 없으면 손잡이 없는 기본 th
  if (!onResize || resizeWidth == null) {
    return (
      <th style={style} {...restThProps}>
        {children}
      </th>
    )
  }

  const mergedStyle: CSSProperties = { ...style, position: 'relative' }
  const handleStyle: CSSProperties = {
    position: 'absolute',
    right: 0,
    top: 0,
    bottom: 0,
    width: 8,
    cursor: 'col-resize',
    userSelect: 'none',
    zIndex: 1,
  }

  return (
    <th style={mergedStyle} {...restThProps}>
      {children}
      <span
        aria-hidden
        style={handleStyle}
        onMouseDown={handleMouseDown}
        onClick={(event) => event.stopPropagation()}
      />
    </th>
  )
}

/** 컬럼 너비 상태와 리사이즈 연동 속성을 반환하는 훅.
 *
 * 컴포넌트 초기에 불리고, 이후 columns 배열을 만들 때 `buildHeaderCellProps(key)`로
 * 각 컬럼의 onHeaderCell을 채워 넣는다. 훅 호출은 early-return보다 앞서야 하므로
 * columns 자체가 아닌 `{key: defaultWidth}` 맵만 요구한다.
 *
 * 사용 예:
 *   const { widthByKey, buildHeaderCellProps, tableComponents } =
 *     useResizableColumnWidths({ split: 100, class_info: 280 })
 *   const columns = [
 *     { key: 'split', width: widthByKey.split, onHeaderCell: buildHeaderCellProps('split'), ... },
 *     ...
 *   ]
 *   <Table columns={columns} components={tableComponents} />
 */
export function useResizableColumnWidths<Key extends string>(
  defaultWidthByKey: Record<Key, number>,
) {
  const [widthByKey, setWidthByKey] = useState<Record<string, number>>(() => ({
    ...defaultWidthByKey,
  }))

  const updateWidth = useCallback((columnKey: string, nextWidth: number) => {
    setWidthByKey((prev) =>
      prev[columnKey] === nextWidth ? prev : { ...prev, [columnKey]: nextWidth },
    )
  }, [])

  /** 컬럼 정의의 onHeaderCell 값을 만들어 준다. 현재 너비 스냅샷 + onResize 콜백. */
  const buildHeaderCellProps = useCallback(
    (columnKey: string) => {
      const currentWidth = widthByKey[columnKey]
      return () =>
        ({
          resizeWidth: currentWidth,
          onResize: (nextWidth: number) => updateWidth(columnKey, nextWidth),
        }) as unknown as React.HTMLAttributes<HTMLElement>
    },
    [widthByKey, updateWidth],
  )

  const tableComponents = {
    header: {
      cell: ResizableHeaderCell as unknown as React.ComponentType<unknown>,
    },
  }

  return { widthByKey, buildHeaderCellProps, tableComponents }
}
