"""
파이프라인 DAG를 Graphviz로 시각화하여 PNG로 저장한다.

파이프라인 실행 시점(Celery 태스크 시작 직후)에 호출되어,
출력 데이터셋 폴더에 pipeline.png를 생성한다.

나중에 PipelineExecution.config 포맷이 변경되어
DB에서 시각화가 불가능해질 때의 폴백용 보험 역할.
"""
from __future__ import annotations

import logging
from pathlib import Path

from lib.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


def render_pipeline_png(
    pipeline_config: PipelineConfig,
    output_path: Path,
    source_dataset_names: dict[str, str] | None = None,
) -> Path | None:
    """
    PipelineConfig를 Graphviz DAG로 렌더링하여 PNG 파일로 저장한다.

    Args:
        pipeline_config: 파이프라인 설정
        output_path: PNG 저장 경로 (확장자 포함, 예: /mnt/datasets/.../pipeline.png)
        source_dataset_names: source dataset_id → 표시 이름 매핑 (없으면 ID 앞 8자리 사용)

    Returns:
        생성된 PNG 파일 경로. 실패 시 None.
    """
    try:
        import graphviz
    except ImportError:
        logger.warning("graphviz 패키지가 없어 pipeline.png를 생성할 수 없습니다.")
        return None

    if source_dataset_names is None:
        source_dataset_names = {}

    try:
        dot = graphviz.Digraph(
            name="pipeline",
            format="png",
            graph_attr={
                "rankdir": "TB",
                "bgcolor": "white",
                "fontname": "sans-serif",
                "pad": "0.5",
                "nodesep": "0.6",
                "ranksep": "0.8",
            },
            node_attr={
                "fontname": "sans-serif",
                "fontsize": "11",
                "style": "filled",
                "shape": "box",
                "penwidth": "1.2",
            },
            edge_attr={
                "fontname": "sans-serif",
                "fontsize": "9",
                "color": "#666666",
                "arrowsize": "0.8",
            },
        )

        # 소스 데이터셋 노드 (회색 계열, 둥근 모서리)
        source_ids_seen: set[str] = set()
        for task_config in pipeline_config.tasks.values():
            for dataset_id in task_config.get_source_dataset_ids():
                if dataset_id in source_ids_seen:
                    continue
                source_ids_seen.add(dataset_id)
                display_name = source_dataset_names.get(
                    dataset_id, dataset_id[:8]
                )
                dot.node(
                    f"src_{dataset_id}",
                    label=display_name,
                    fillcolor="#E8E8E8",
                    color="#999999",
                    shape="box",
                    style="filled,rounded",
                )

        # 태스크 노드 (파란 계열)
        for task_name, task_config in pipeline_config.tasks.items():
            label_lines = [task_name, f"({task_config.operator})"]
            # 주요 파라미터 표시 (최대 3개)
            if task_config.params:
                param_lines = []
                for key, value in list(task_config.params.items())[:3]:
                    value_str = str(value)
                    if len(value_str) > 25:
                        value_str = value_str[:22] + "..."
                    param_lines.append(f"{key}={value_str}")
                if param_lines:
                    label_lines.append("─" * 16)
                    label_lines.extend(param_lines)
                if len(task_config.params) > 3:
                    label_lines.append(f"... +{len(task_config.params) - 3}")

            dot.node(
                f"task_{task_name}",
                label="\n".join(label_lines),
                fillcolor="#DBEAFE",
                color="#3B82F6",
            )

        # 출력 노드 (초록 계열)
        output_config = pipeline_config.output
        output_label = (
            f"{pipeline_config.name}\n"
            f"{output_config.dataset_type} / {output_config.split}"
        )
        if output_config.annotation_format:
            output_label += f"\n({output_config.annotation_format})"
        dot.node(
            "output",
            label=output_label,
            fillcolor="#D1FAE5",
            color="#10B981",
            shape="box",
            style="filled,rounded",
            penwidth="2",
        )

        # 엣지: 소스 → 태스크
        for task_name, task_config in pipeline_config.tasks.items():
            for dataset_id in task_config.get_source_dataset_ids():
                dot.edge(f"src_{dataset_id}", f"task_{task_name}")
            for dep_task in task_config.get_dependency_task_names():
                dot.edge(f"task_{dep_task}", f"task_{task_name}")

        # 엣지: 최종 태스크 → 출력
        terminal_task_name = pipeline_config.get_terminal_task_name()
        dot.edge(f"task_{terminal_task_name}", "output")

        # PNG 렌더링
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # graphviz의 render()는 확장자를 자동 붙이므로, stem만 전달
        rendered_path = dot.render(
            filename=str(output_path.with_suffix("")),
            cleanup=True,
        )
        logger.info("pipeline.png 생성 완료: %s", rendered_path)
        return Path(rendered_path)

    except Exception as render_error:
        logger.warning(
            "pipeline.png 생성 실패: %s",
            str(render_error),
            exc_info=True,
        )
        return None
