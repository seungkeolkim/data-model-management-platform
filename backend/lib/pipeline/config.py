"""
파이프라인 실행 설정 스키마 (DAG 기반).

Pydantic BaseModel로 정의하되, DB/FastAPI에 의존하지 않는 순수 설정.
app/schemas/pipeline.py에서 re-export하여 API 레이어에서도 사용한다.

YAML 구조 (schema_version=2, v7.10 — 2안 run-time version 해석):
    pipeline:
      name: "출력 그룹명"
      description: "설명"
      output:
        dataset_type: SOURCE
        annotation_format: COCO
        split: TRAIN
      tasks:
        task_name:
          operator: det_format_convert_to_coco
          inputs: ["source:<split_id>"]
          params: { ... }
      passthrough_source_split_id: "<split_id>"
      schema_version: 2

Pipeline 엔티티 config 로 저장되며, 실제 실행 시 Version Resolver Modal 이
`{split_id: version}` 을 확정해 `PipelineRun.resolved_input_versions` 에 저장. 즉
"어느 split 을 쓰는가" 는 Pipeline 이, "어느 version 을 썼는가" 는 Run 이 보유.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


# 현재 SDK 가 생성하고 backend 가 받는 PipelineConfig schema 버전.
CURRENT_SCHEMA_VERSION: int = 2


class TaskConfig(BaseModel):
    """DAG 내 하나의 태스크 설정."""
    operator: str = Field(..., description="MANIPULATOR_REGISTRY 키")
    inputs: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "입력 참조 목록. "
            "'source:<dataset_id>' = DB 데이터셋, "
            "태스크명 = 이전 태스크 출력"
        ),
    )
    params: dict[str, Any] = Field(default_factory=dict)

    def get_source_dataset_ids(self) -> list[str]:
        """inputs 중 'source:' 접두사를 가진 dataset_id 목록 반환."""
        return [
            ref.split(":", 1)[1]
            for ref in self.inputs
            if ref.startswith("source:")
        ]

    def get_dependency_task_names(self) -> list[str]:
        """inputs 중 다른 태스크를 참조하는 이름 목록 반환."""
        return [
            ref for ref in self.inputs
            if not ref.startswith("source:")
        ]


class OutputConfig(BaseModel):
    """파이프라인 출력 설정."""
    dataset_type: str = Field(
        default="SOURCE",
        description="SOURCE | PROCESSED | FUSION",
    )
    annotation_format: str = Field(
        ...,
        description="출력 annotation 포맷 (COCO | YOLO). 통일포맷이므로 반드시 지정 필요.",
    )
    split: str = Field(
        default="NONE",
        description="TRAIN | VAL | TEST | NONE",
    )


class PipelineConfig(BaseModel):
    """
    DAG 기반 파이프라인 실행 전체 설정.

    tasks는 dict[태스크명, TaskConfig]로 정의되며,
    각 태스크의 inputs 필드로 의존 관계(DAG)를 형성한다.
    실행 순서는 topological sort로 자동 결정.
    """
    name: str = Field(..., description="출력 DatasetGroup 이름")
    description: str | None = None
    output: OutputConfig
    # tasks 는 비어있을 수 있다 (DataLoad → Save 직결, passthrough 모드).
    # 그 경우 passthrough_source_split_id 가 반드시 채워져 있어야 한다.
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)
    # passthrough 모드 (Load→Save 직결, tasks 비어있음) 에서 사용할 소스 split.
    # FE / 사용자가 작성하는 spec — split 까지만 고정.
    passthrough_source_split_id: str | None = Field(
        default=None,
        description="passthrough 모드의 소스 DatasetSplit.id",
    )
    # backend submit 시점에 채워지는 resolved 필드 — 실제 DatasetVersion.id.
    # PipelineRun.transform_config 스냅샷 / dag_executor 가 이걸 읽어 데이터를 로드한다.
    # FE 는 항상 None 으로 보내며, submit 단계에서 Version Resolver 결과로 치환된다.
    passthrough_source_dataset_id: str | None = Field(
        default=None,
        description="(resolved) passthrough 의 DatasetVersion.id — backend submit 단계에서 채움",
    )
    # DAG schema 버전. FE SDK 가 config 생성 시 기입. 현재는 항상 2.
    # 미래 변경 대비 완충 필드.
    schema_version: int | None = Field(
        default=None,
        description="DAG schema 버전 (현재 2 만 허용)",
    )

    @model_validator(mode="after")
    def _validate_tasks_or_passthrough(self) -> PipelineConfig:
        """tasks 가 비어있으면 passthrough_source_split_id 가 반드시 채워져야 한다."""
        if not self.tasks and not self.passthrough_source_split_id:
            raise ValueError(
                "tasks 가 비어있을 경우 passthrough_source_split_id 가 필요합니다 "
                "(Load→Save 직결 모드)."
            )
        return self

    @model_validator(mode="after")
    def _validate_task_references(self) -> PipelineConfig:
        """모든 태스크의 inputs가 유효한 참조(source: 또는 다른 태스크명)인지 검증."""
        task_names = set(self.tasks.keys())
        for task_name, task_config in self.tasks.items():
            for ref in task_config.get_dependency_task_names():
                if ref not in task_names:
                    raise ValueError(
                        f"태스크 '{task_name}'의 input '{ref}'가 "
                        f"정의된 태스크 목록에 없습니다: {sorted(task_names)}"
                    )
            # 자기 자신 참조 금지
            if task_name in task_config.get_dependency_task_names():
                raise ValueError(
                    f"태스크 '{task_name}'이 자기 자신을 input으로 참조합니다."
                )
        return self

    @model_validator(mode="after")
    def _validate_no_cycle(self) -> PipelineConfig:
        """DAG에 순환 참조가 없는지 검증 (Kahn's algorithm)."""
        # 인접 리스트 + 진입 차수 계산
        in_degree: dict[str, int] = {name: 0 for name in self.tasks}
        adjacency: dict[str, list[str]] = {name: [] for name in self.tasks}

        for task_name, task_config in self.tasks.items():
            for dep in task_config.get_dependency_task_names():
                adjacency[dep].append(task_name)
                in_degree[task_name] += 1

        # 진입 차수 0인 노드부터 시작
        queue = [name for name, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            current = queue.pop(0)
            visited_count += 1
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(self.tasks):
            raise ValueError(
                "파이프라인 태스크에 순환 참조가 있습니다. "
                "DAG 구조를 확인하세요."
            )
        return self

    def topological_order(self) -> list[str]:
        """태스크를 의존 관계 순서대로 정렬하여 반환 (Kahn's algorithm)."""
        in_degree: dict[str, int] = {name: 0 for name in self.tasks}
        adjacency: dict[str, list[str]] = {name: [] for name in self.tasks}

        for task_name, task_config in self.tasks.items():
            for dep in task_config.get_dependency_task_names():
                adjacency[dep].append(task_name)
                in_degree[task_name] += 1

        queue = sorted(
            [name for name, deg in in_degree.items() if deg == 0]
        )
        order: list[str] = []

        while queue:
            current = queue.pop(0)
            order.append(current)
            for neighbor in sorted(adjacency[current]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    def get_all_source_split_ids(self) -> list[str]:
        """
        파이프라인 전체에서 참조하는 모든 source DatasetSplit.id 를 중복 제거 반환.
        passthrough 모드는 passthrough_source_split_id 도 포함.

        FE / 사용자가 작성한 spec 의 split-level 참조를 가져올 때 사용.
        """
        seen: set[str] = set()
        result: list[str] = []
        if self.passthrough_source_split_id:
            seen.add(self.passthrough_source_split_id)
            result.append(self.passthrough_source_split_id)
        for task_config in self.tasks.values():
            for split_id in task_config.get_source_dataset_ids():
                if split_id not in seen:
                    seen.add(split_id)
                    result.append(split_id)
        return result

    def get_all_source_dataset_ids(self) -> list[str]:
        """
        executor 가 보는 resolved DatasetVersion.id 들 — submit 단계에서 split_id 가
        dataset_version_id 로 치환된 후의 transform_config 에서 호출된다.

        config.tasks[*].inputs 의 `source:<X>` 와 `passthrough_source_dataset_id` 의 X 값을
        반환. 호출 시점이 spec 단계인지 resolved 단계인지에 따라 X 의 의미가 달라지므로
        호출부에서 의도를 명확히 할 것:
          - spec 단계: source ref 가 split_id → get_all_source_split_ids 사용
          - resolved 단계: source ref 가 dataset_version_id → 이 메서드 사용 (executor)
        """
        seen: set[str] = set()
        result: list[str] = []
        if self.passthrough_source_dataset_id:
            seen.add(self.passthrough_source_dataset_id)
            result.append(self.passthrough_source_dataset_id)
        for task_config in self.tasks.values():
            for source_id in task_config.get_source_dataset_ids():
                if source_id not in seen:
                    seen.add(source_id)
                    result.append(source_id)
        return result

    @property
    def is_passthrough(self) -> bool:
        """Load→Save 직결 모드 (tasks 비어있음) 여부."""
        return len(self.tasks) == 0

    def get_terminal_task_name(self) -> str:
        """
        DAG의 최종 출력 태스크(sink 노드)를 반환.
        다른 태스크의 input으로 참조되지 않는 유일한 태스크.

        Raises:
            ValueError: sink 노드가 0개 또는 2개 이상일 때
        """
        referenced_as_input: set[str] = set()
        for task_config in self.tasks.values():
            referenced_as_input.update(task_config.get_dependency_task_names())

        terminal_tasks = [
            name for name in self.tasks
            if name not in referenced_as_input
        ]

        if len(terminal_tasks) == 0:
            raise ValueError("최종 출력 태스크(sink 노드)가 없습니다.")
        if len(terminal_tasks) > 1:
            raise ValueError(
                f"최종 출력 태스크가 2개 이상입니다: {terminal_tasks}. "
                "det_merge_datasets 등으로 하나로 합쳐야 합니다."
            )
        return terminal_tasks[0]


class PartialPipelineConfig(BaseModel):
    """
    Save 노드 없이도 유효한 부분 파이프라인 설정.

    JSON 프리뷰, schema 프리뷰 등 "실행 전 미리보기" 용도로 사용한다.
    output / name 이 없어도 tasks + source 참조만 있으면 유효.
    PipelineConfig 를 상속하지 않고 별도 정의하여 실행 경로와 격리한다.
    """
    name: str = Field(default="<draft>", description="출력 DatasetGroup 이름 (임시)")
    description: str | None = None
    output: OutputConfig | None = Field(
        default=None,
        description="출력 설정. Save 노드가 없으면 null.",
    )
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)
    passthrough_source_split_id: str | None = None
    passthrough_source_dataset_id: str | None = None  # resolved (executor 호환)
    schema_version: int | None = None

    @model_validator(mode="after")
    def _validate_task_references(self) -> PartialPipelineConfig:
        """모든 태스크의 inputs 가 유효한 참조인지 검증."""
        task_names = set(self.tasks.keys())
        for task_name, task_config in self.tasks.items():
            for ref in task_config.get_dependency_task_names():
                if ref not in task_names:
                    raise ValueError(
                        f"태스크 '{task_name}'의 input '{ref}'가 "
                        f"정의된 태스크 목록에 없습니다: {sorted(task_names)}"
                    )
            if task_name in task_config.get_dependency_task_names():
                raise ValueError(
                    f"태스크 '{task_name}'이 자기 자신을 input으로 참조합니다."
                )
        return self

    @model_validator(mode="after")
    def _validate_no_cycle(self) -> PartialPipelineConfig:
        """DAG 순환 참조 검증."""
        in_degree: dict[str, int] = {name: 0 for name in self.tasks}
        adjacency: dict[str, list[str]] = {name: [] for name in self.tasks}
        for task_name, task_config in self.tasks.items():
            for dep in task_config.get_dependency_task_names():
                adjacency[dep].append(task_name)
                in_degree[task_name] += 1
        queue = [name for name, deg in in_degree.items() if deg == 0]
        visited_count = 0
        while queue:
            current = queue.pop(0)
            visited_count += 1
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        if visited_count != len(self.tasks):
            raise ValueError("파이프라인 태스크에 순환 참조가 있습니다.")
        return self

    def topological_order(self) -> list[str]:
        """태스크를 의존 관계 순서대로 정렬 (Kahn's algorithm)."""
        in_degree: dict[str, int] = {name: 0 for name in self.tasks}
        adjacency: dict[str, list[str]] = {name: [] for name in self.tasks}
        for task_name, task_config in self.tasks.items():
            for dep in task_config.get_dependency_task_names():
                adjacency[dep].append(task_name)
                in_degree[task_name] += 1
        queue = sorted([name for name, deg in in_degree.items() if deg == 0])
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for neighbor in sorted(adjacency[current]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    def get_all_source_split_ids(self) -> list[str]:
        """파이프라인 전체에서 참조하는 모든 source DatasetSplit.id 를 중복 제거 반환."""
        seen: set[str] = set()
        result: list[str] = []
        if self.passthrough_source_split_id:
            seen.add(self.passthrough_source_split_id)
            result.append(self.passthrough_source_split_id)
        for task_config in self.tasks.values():
            for split_id in task_config.get_source_dataset_ids():
                if split_id not in seen:
                    seen.add(split_id)
                    result.append(split_id)
        return result


def extract_source_split_ids(
    config: PipelineConfig | PartialPipelineConfig,
) -> list[str]:
    """
    핸드오프 027 §12-9 의 순수 헬퍼. config 가 참조하는 모든 source DatasetSplit.id 를
    중복 제거해 반환. chaining 분석기 / automation triggering 훅 / "이 split 을 쓰는
    Pipeline 찾기" UI filter 에서 재사용.
    """
    return config.get_all_source_split_ids()


def load_pipeline_config_from_yaml(yaml_path: str | Path) -> PipelineConfig:
    """
    YAML 파일을 읽어서 PipelineConfig로 파싱.

    YAML 최상위 키는 'pipeline'이어야 한다.
    예:
        pipeline:
          name: "my_pipeline"
          output:
            dataset_type: SOURCE
            split: TRAIN
          tasks:
            convert:
              operator: det_format_convert_to_coco
              inputs: ["source:abc-123"]
              params: {}

    Args:
        yaml_path: YAML 파일 경로

    Returns:
        파싱된 PipelineConfig
    """
    yaml_path = Path(yaml_path)
    with open(yaml_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "pipeline" not in raw:
        raise ValueError(
            f"YAML 파일의 최상위 키가 'pipeline'이어야 합니다: {yaml_path}"
        )

    return PipelineConfig(**raw["pipeline"])
