"""
CLS_MANIFEST 포맷 파서 및 라이터.

디스크 레이아웃 (dataset storage_uri 하위):
    images/{filename}         # 이미지 풀. 이미지 identity = filename.
    manifest.jsonl            # 이미지 1장당 1줄. 메타/라벨 기록.
    head_schema.json          # head 정의 (SSOT — classes 순서가 output index 와 일치)

manifest.jsonl 1줄 스키마 (§2-12 확정: null=unknown, []=explicit empty):
    {
      "filename": "images/img_0001.jpg",
      "original_filename": "img_0001.jpg",
      "labels": {"hardhat_wear": ["helmet"], "visibility": null}
    }

head_schema.json 스키마 (SSOT — objective_n_plan_7th.md):
    {
      "heads": [
        {"name": "hardhat_wear", "multi_label": false, "classes": ["helmet", "no_helmet"]},
        ...
      ]
    }

파싱/저장 원칙:
  - 이 모듈은 파일 I/O 만 수행. DB/FastAPI 의존성 금지.
  - 이미지 바이너리는 건드리지 않는다 (실체화는 ImageMaterializer 담당).
  - 파서는 manifest.jsonl 라인 순서를 보존해 image_records 에 담는다.
  - 라이터는 DatasetMeta.image_records 순서대로 manifest.jsonl 을 작성한다.
  - 이미지 identity 는 filename (과거 SHA 기반 content identity 는 폐지됨).
"""
from __future__ import annotations

import json
from pathlib import Path

from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord


MANIFEST_FILENAME = "manifest.jsonl"
HEAD_SCHEMA_FILENAME = "head_schema.json"


def parse_manifest_dir(
    dataset_root: Path,
    dataset_id: str = "",
    storage_uri: str = "",
) -> DatasetMeta:
    """
    Classification 데이터셋 루트에서 manifest.jsonl + head_schema.json 을 읽어 DatasetMeta 로 변환한다.

    Args:
        dataset_root: 데이터셋 절대 경로. 하위에 manifest.jsonl 과 head_schema.json 이 있어야 한다.
        dataset_id:   DatasetMeta.dataset_id 에 채울 값 (선택).
        storage_uri:  DatasetMeta.storage_uri 에 채울 값 (선택).

    Returns:
        head_schema 가 세팅된 Classification 모드 DatasetMeta.

    Raises:
        FileNotFoundError: manifest.jsonl 또는 head_schema.json 이 없을 때.
        ValueError:        JSON 파싱 실패 또는 필수 필드 누락 시.
    """
    manifest_path = dataset_root / MANIFEST_FILENAME
    schema_path = dataset_root / HEAD_SCHEMA_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.jsonl 이 존재하지 않습니다: {manifest_path}")
    if not schema_path.exists():
        raise FileNotFoundError(f"head_schema.json 이 존재하지 않습니다: {schema_path}")

    # head_schema.json 파싱 — 규약: {"heads": [...]} dict 형태 (objective_n_plan_7th.md:142)
    with open(schema_path, "r", encoding="utf-8") as schema_file:
        raw_schema = json.load(schema_file)
    if not isinstance(raw_schema, dict) or "heads" not in raw_schema:
        raise ValueError(
            f"head_schema.json 은 {{\"heads\": [...]}} 형태여야 합니다: {schema_path}"
        )
    raw_heads = raw_schema["heads"]
    if not isinstance(raw_heads, list):
        raise ValueError(
            f"head_schema.json 의 'heads' 값은 list 여야 합니다: {schema_path}"
        )
    head_schema: list[HeadSchema] = []
    for raw_head in raw_heads:
        if not isinstance(raw_head, dict):
            raise ValueError(f"head_schema 항목이 dict 가 아닙니다: {raw_head!r}")
        try:
            head_schema.append(
                HeadSchema(
                    name=raw_head["name"],
                    multi_label=bool(raw_head.get("multi_label", False)),
                    classes=list(raw_head["classes"]),
                )
            )
        except KeyError as missing_key:
            raise ValueError(
                f"head_schema 항목에 필수 키 {missing_key} 가 없습니다: {raw_head!r}"
            ) from missing_key

    # manifest.jsonl 라인별 파싱
    image_records: list[ImageRecord] = []
    for line_number, raw_line in _iter_manifest_lines(manifest_path):
        try:
            line_data = json.loads(raw_line)
        except json.JSONDecodeError as json_error:
            raise ValueError(
                f"manifest.jsonl {line_number}행 JSON 파싱 실패: {json_error}"
            ) from json_error

        filename_value = line_data.get("filename")
        if not filename_value:
            raise ValueError(
                f"manifest.jsonl {line_number}행에 filename 필드가 없습니다: {line_data}"
            )

        labels_value = line_data.get("labels", {}) or {}
        if not isinstance(labels_value, dict):
            raise ValueError(
                f"manifest.jsonl {line_number}행 labels 는 dict 여야 합니다: {labels_value!r}"
            )
        # null=unknown(None), []=explicit empty, [class,...]=known labels. §2-12 확정 규약.
        normalized_labels: dict[str, list[str] | None] = {}
        for head_name, label_value in labels_value.items():
            if label_value is None:
                normalized_labels[head_name] = None
            elif isinstance(label_value, list):
                normalized_labels[head_name] = [str(item) for item in label_value]
            else:
                normalized_labels[head_name] = [str(label_value)]

        # image_id 는 filename 자체를 사용 (파이프라인 내부에서 이미지 식별자 역할).
        image_records.append(
            ImageRecord(
                image_id=filename_value,
                file_name=filename_value,
                labels=normalized_labels,
                extra={
                    "original_filename": line_data.get("original_filename"),
                },
            )
        )

    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=storage_uri,
        categories=[],
        head_schema=head_schema,
        image_records=image_records,
    )


def _iter_manifest_lines(manifest_path: Path):
    """빈 줄을 건너뛰며 (line_number, stripped_line) 을 yield."""
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        for line_number, raw_line in enumerate(manifest_file, start=1):
            stripped_line = raw_line.strip()
            if not stripped_line:
                continue
            yield line_number, stripped_line


def write_manifest_dir(meta: DatasetMeta, dataset_root: Path) -> None:
    """
    Classification DatasetMeta 를 디스크에 기록한다.

    이 함수는 manifest.jsonl + head_schema.json 만 작성한다.
    images/ 하위 바이너리 파일은 ImageMaterializer 가 별도로 배치한다.

    Args:
        meta: head_schema 가 설정된 Classification 모드 DatasetMeta.
        dataset_root: 출력 데이터셋 루트 (미리 mkdir 되어 있어야 한다).

    Raises:
        ValueError: meta.head_schema 가 None 일 때 (detection 모드에서 잘못 호출).
    """
    if meta.head_schema is None:
        raise ValueError(
            "write_manifest_dir 는 classification DatasetMeta 에만 사용합니다 "
            "(head_schema 가 None 입니다)."
        )

    schema_path = dataset_root / HEAD_SCHEMA_FILENAME
    # 규약: {"heads": [...]} dict 형태 (RAW 등록 writer 와 동일, objective_n_plan_7th.md:142)
    serialized_schema = {
        "heads": [
            {
                "name": head.name,
                "multi_label": head.multi_label,
                "classes": list(head.classes),
            }
            for head in meta.head_schema
        ]
    }
    with open(schema_path, "w", encoding="utf-8") as schema_file:
        json.dump(serialized_schema, schema_file, ensure_ascii=False, indent=2)

    # single-label head 이름 집합 — writer assert 용.
    single_label_head_names = {
        head.name for head in meta.head_schema if not head.multi_label
    }

    manifest_path = dataset_root / MANIFEST_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        for record in meta.image_records:
            record_labels = record.labels or {}

            # §2-12 writer strict assert: single-label head 는 null 또는 [class 1개]만 허용.
            for head_name in single_label_head_names:
                label_value = record_labels.get(head_name)
                if label_value is not None and len(label_value) != 1:
                    raise ValueError(
                        f"single-label head '{head_name}': labels 는 null(unknown) "
                        f"또는 [class 1개] 여야 합니다, got {label_value!r} "
                        f"(file_name={record.file_name})"
                    )

            line_obj = {
                "filename": record.file_name,
                "original_filename": (record.extra or {}).get("original_filename"),
                "labels": record_labels,
            }
            manifest_file.write(json.dumps(line_obj, ensure_ascii=False))
            manifest_file.write("\n")
