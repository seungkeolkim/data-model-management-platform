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

/** 컬럼 최소 너비(px). 너무 좁아지지 않도록 가드. */
const MINIMUM_COLUMN_WIDTH_PX = 60

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

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const deltaPx = moveEvent.clientX - dragStartClientXRef.current
        const nextWidth = Math.max(
          MINIMUM_COLUMN_WIDTH_PX,
          dragStartWidthRef.current + deltaPx,
        )
        onResize(nextWidth)
      }
      const handleMouseUp = () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
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
