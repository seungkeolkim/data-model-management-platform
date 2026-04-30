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
      // 이유: 매 mousemove 마다 setWidthByKey → 전 행 × 전 열 re-render 가 일어나면
      //       특히 최좌측 컬럼처럼 우측에 따라오는 셀이 많은 경우 60fps 를 못 따라가
      //       cursor 와 column edge 사이에 가시 가능한 지연이 생긴다.
      // table-layout: fixed 에서는 `<colgroup>` 의 `<col>` 이 컬럼 너비의 SSOT 이고
      // `<th>` 는 보조이므로 두 곳 모두 inline style 로 갱신.
      // mouseup 시점에 onResize(lastWidth) 1회 호출로 React state 와 DOM 을 일치.
      const handleSpan = event.currentTarget
      const thEl = handleSpan.parentElement as HTMLTableCellElement | null
      const tableEl = thEl?.closest('table') as HTMLTableElement | null
      const colgroupEl = tableEl?.querySelector('colgroup') ?? null
      const cellIndex = thEl ? thEl.cellIndex : -1
      const colEl =
        cellIndex >= 0 && colgroupEl
          ? (colgroupEl.children[cellIndex] as HTMLElement | undefined) ?? null
          : null

      // 드래그 실제 발생 여부 + 마지막으로 적용한 폭. mouseup 에서 사용.
      let didActuallyDrag = false
      let lastNextWidth = dragStartWidthRef.current

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const deltaPx = moveEvent.clientX - dragStartClientXRef.current
        if (deltaPx !== 0) didActuallyDrag = true
        const nextWidth = Math.max(
          MINIMUM_COLUMN_WIDTH_PX,
          dragStartWidthRef.current + deltaPx,
        )
        lastNextWidth = nextWidth
        // DOM 직접 갱신 — React 재렌더 없이 즉시 layout 반영.
        if (colEl) colEl.style.width = `${nextWidth}px`
        if (thEl) thEl.style.width = `${nextWidth}px`
      }
      const handleMouseUp = () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
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
