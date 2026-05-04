#!/usr/bin/env bash
# =============================================================================
# ML Platform - 초기 RAW 데이터셋 등록 스크립트
#
# 목적
#   DB를 초기화 (예: make db-reset) 한 직후, 현재 NAS / 업로드 경로에 존재하는
#   원본 데이터를 GUI 와 동일한 API 호출 (`/api/v1/dataset-groups/register`,
#   `/api/v1/dataset-groups/register-classification`) 로 다시 등록한다.
#
#   이 스크립트는 DB 에 row 만 만드는 것이 아니라 정식 등록 플로우를 그대로
#   타기 때문에, 백엔드가 LOCAL_UPLOAD_BASE → LOCAL_STORAGE_BASE 로 파일을
#   복사하고 manifest / head_schema 등을 정상적으로 생성한다 (Celery 비동기).
#
# 전제
#   1) `.env` 의 LOCAL_UPLOAD_BASE 가 /hdd1/data-platform/uploads (또는 동일
#      구조를 가진 NAS 경로) 로 설정돼 있어야 한다.
#   2) 컨테이너 내부에서 LOCAL_UPLOAD_BASE 는 /mnt/uploads 로 마운트 되므로,
#      API 요청에 넘기는 경로는 모두 /mnt/uploads/... 형태이다.
#   3) make up 으로 backend, celery, postgres, nginx 가 모두 떠 있어야 한다.
#
# 등록되는 5개 그룹 (현재 DB 스냅샷 기준)
#   - coco2017         (RAW / COCO          / DETECTION)       VAL 1.0, TRAIN 1.0
#   - coco8_yolo       (RAW / YOLO          / DETECTION)       TRAIN 1.0/2.0, VAL 1.0
#   - coco128_yolo     (RAW / YOLO          / DETECTION)       TRAIN 1.0
#   - hardhat_orig     (RAW / CLS_MANIFEST  / CLASSIFICATION)  TRAIN/VAL/TEST 1.0
#   - hardhat_headcrop (RAW / CLS_MANIFEST  / CLASSIFICATION)  TRAIN/VAL/TEST 1.0
#
# 사용법
#   ./scripts/create_initial_datasets.sh                # 전체 그룹 순차 등록
#   API_BASE=http://localhost:18080 ./scripts/create_initial_datasets.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# 환경 변수 / 기본 경로
# ---------------------------------------------------------------------------
API_BASE="${API_BASE:-http://localhost:18080}"

# .env 의 LOCAL_UPLOAD_BASE 를 읽어와 호스트 경로로 검증한다.
# 컨테이너 내부 경로는 항상 /mnt/uploads 로 고정.
HOST_UPLOAD_BASE="$(grep -E '^LOCAL_UPLOAD_BASE=' "${PROJECT_ROOT}/.env" 2>/dev/null | cut -d= -f2- || true)"
HOST_UPLOAD_BASE="${HOST_UPLOAD_BASE:-/hdd1/data-platform/uploads}"
CONTAINER_UPLOAD_BASE="/mnt/uploads"

# ---------------------------------------------------------------------------
# 색상 로그 헬퍼
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()       { log_error "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 사전 점검
# ---------------------------------------------------------------------------
command -v curl >/dev/null || die "curl 이 필요합니다."
command -v jq   >/dev/null || die "jq 가 필요합니다. (sudo apt-get install jq)"

[[ -d "$HOST_UPLOAD_BASE" ]] || die "LOCAL_UPLOAD_BASE 경로가 존재하지 않습니다: $HOST_UPLOAD_BASE"

log_info "API_BASE              = $API_BASE"
log_info "HOST_UPLOAD_BASE      = $HOST_UPLOAD_BASE"
log_info "CONTAINER_UPLOAD_BASE = $CONTAINER_UPLOAD_BASE"

# 백엔드 healthcheck — 최대 30초 대기
log_info "백엔드 health check 대기..."
for attempt in $(seq 1 30); do
    if curl -sf "${API_BASE}/api/v1/health" >/dev/null 2>&1 \
        || curl -sf "${API_BASE}/health"        >/dev/null 2>&1 \
        || curl -sf "${API_BASE}/api/v1/dataset-groups" >/dev/null 2>&1; then
        log_ok "백엔드 응답 확인 (attempt=$attempt)"
        break
    fi
    if [[ $attempt -eq 30 ]]; then
        die "백엔드가 30초 동안 응답하지 않습니다. make up 상태를 확인하세요."
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 호스트 경로 검증 + 컨테이너 경로 변환
#
# 호스트 절대경로 (예: /hdd1/data-platform/uploads/coco8/images/train) →
# 컨테이너 절대경로 (예: /mnt/uploads/coco8/images/train).
# 등록 API 는 컨테이너 내부 경로를 받기 때문에 이 변환이 필수.
# ---------------------------------------------------------------------------
to_container_path() {
    local host_path="$1"
    case "$host_path" in
        "${HOST_UPLOAD_BASE}"/*)
            echo "${CONTAINER_UPLOAD_BASE}/${host_path#${HOST_UPLOAD_BASE}/}"
            ;;
        "${HOST_UPLOAD_BASE}")
            echo "${CONTAINER_UPLOAD_BASE}"
            ;;
        *)
            die "호스트 경로가 LOCAL_UPLOAD_BASE 하위가 아닙니다: $host_path"
            ;;
    esac
}

assert_exists_dir() {
    [[ -d "$1" ]] || die "디렉토리가 없습니다: $1"
}
assert_exists_file() {
    [[ -f "$1" ]] || die "파일이 없습니다: $1"
}

# ---------------------------------------------------------------------------
# Detection (COCO / YOLO) 등록 헬퍼
#
# 인자
#   $1 group_name            (group_id 가 없으면 신규 생성용 이름)
#   $2 group_id_or_empty     ("" 이면 새 그룹)
#   $3 split                 TRAIN | VAL | TEST | NONE
#   $4 annotation_format     COCO | YOLO
#   $5 task_type             DETECTION | SEGMENTATION ...
#   $6 host_image_dir        호스트 절대경로
#   $7 host_meta_file_or_empty  YOLO data.yaml 같은 메타 파일 (없으면 "")
#   $8.. host_annotation_files... (가변 인자, 1개 이상)
#
# 동작
#   - 호스트 경로의 존재 여부 검증
#   - 컨테이너 경로로 변환 후 JSON payload 구성
#   - POST /api/v1/dataset-groups/register
#   - 응답에서 group id 를 추출해 stdout 으로 반환
# ---------------------------------------------------------------------------
register_detection() {
    local group_name="$1"
    local group_id="$2"
    local split="$3"
    local annotation_format="$4"
    local task_type="$5"
    local host_image_dir="$6"
    local host_meta_file="$7"
    shift 7
    local host_annotation_files=("$@")

    assert_exists_dir "$host_image_dir"
    if [[ -n "$host_meta_file" ]]; then
        assert_exists_file "$host_meta_file"
    fi
    [[ ${#host_annotation_files[@]} -gt 0 ]] || die "어노테이션 파일이 1개 이상 필요합니다 ($group_name $split)."

    local container_image_dir
    container_image_dir="$(to_container_path "$host_image_dir")"

    local container_meta_file_json="null"
    if [[ -n "$host_meta_file" ]]; then
        local cmeta
        cmeta="$(to_container_path "$host_meta_file")"
        container_meta_file_json="$(jq -Rn --arg p "$cmeta" '$p')"
    fi

    # 어노테이션 파일들을 컨테이너 경로 JSON 배열로 변환
    local container_annotation_files_json
    container_annotation_files_json="$(
        for host_file in "${host_annotation_files[@]}"; do
            assert_exists_file "$host_file"
            to_container_path "$host_file"
        done | jq -R . | jq -s .
    )"

    # group_id / group_name 분기 — 첫 등록은 group_name, 이후는 group_id
    local group_field
    if [[ -n "$group_id" ]]; then
        group_field="$(jq -n --arg gid "$group_id" '{group_id: $gid, group_name: null}')"
    else
        group_field="$(jq -n --arg gname "$group_name" '{group_id: null, group_name: $gname}')"
    fi

    local payload
    payload="$(jq -n \
        --argjson group "$group_field" \
        --arg split "$split" \
        --arg annotation_format "$annotation_format" \
        --arg task_type "$task_type" \
        --arg image_dir "$container_image_dir" \
        --argjson annotation_files "$container_annotation_files_json" \
        --argjson meta_file "$container_meta_file_json" \
        '{
            group_id:                $group.group_id,
            group_name:              $group.group_name,
            task_types:              [$task_type],
            annotation_format:       $annotation_format,
            modality:                "RGB",
            split:                   $split,
            source_image_dir:        $image_dir,
            source_annotation_files: $annotation_files,
            source_annotation_meta_file: $meta_file
        }'
    )"

    log_info "[register_detection] $group_name $split ($annotation_format, files=${#host_annotation_files[@]})"

    local http_status response_body tmp_body
    tmp_body="$(mktemp)"
    http_status="$(curl -sS -o "$tmp_body" -w "%{http_code}" \
        -X POST "${API_BASE}/api/v1/dataset-groups/register" \
        -H "Content-Type: application/json" \
        --data "$payload")"
    response_body="$(cat "$tmp_body")"
    rm -f "$tmp_body"

    if [[ "$http_status" != "200" && "$http_status" != "201" && "$http_status" != "202" ]]; then
        log_error "등록 실패: $group_name $split (HTTP $http_status)"
        log_error "응답: $response_body"
        return 1
    fi

    local returned_group_id
    returned_group_id="$(echo "$response_body" | jq -r '.id // empty')"
    [[ -n "$returned_group_id" ]] || { log_error "응답에서 group id 추출 실패: $response_body"; return 1; }

    log_ok "등록 접수: $group_name $split → group_id=$returned_group_id"
    echo "$returned_group_id"
}

# ---------------------------------------------------------------------------
# Classification 등록 헬퍼
#
# 인자
#   $1 group_name
#   $2 group_id_or_empty
#   $3 split
#   $4 host_root_dir              데이터셋 루트 (예: .../hardhat_original/train)
#   $5 heads_spec_json            jq 로 만들어 둔 heads 배열 JSON 문자열
#                                 [{"name":"hardhat_wear","multi_label":false,
#                                   "classes":["0_no_helmet","1_helmet"],
#                                   "source_class_paths":["/mnt/.../0_no_helmet",
#                                                          "/mnt/.../1_helmet"]}, ...]
# ---------------------------------------------------------------------------
register_classification() {
    local group_name="$1"
    local group_id="$2"
    local split="$3"
    local host_root_dir="$4"
    local heads_spec_json="$5"

    assert_exists_dir "$host_root_dir"
    local container_root_dir
    container_root_dir="$(to_container_path "$host_root_dir")"

    local group_field
    if [[ -n "$group_id" ]]; then
        group_field="$(jq -n --arg gid "$group_id" '{group_id: $gid, group_name: null}')"
    else
        group_field="$(jq -n --arg gname "$group_name" '{group_id: null, group_name: $gname}')"
    fi

    local payload
    payload="$(jq -n \
        --argjson group "$group_field" \
        --arg split "$split" \
        --arg root_dir "$container_root_dir" \
        --argjson heads "$heads_spec_json" \
        '{
            group_id:        $group.group_id,
            group_name:      $group.group_name,
            modality:        "RGB",
            split:           $split,
            source_root_dir: $root_dir,
            heads:           $heads
        }'
    )"

    log_info "[register_classification] $group_name $split (heads=$(echo "$heads_spec_json" | jq 'length'))"

    local http_status response_body tmp_body
    tmp_body="$(mktemp)"
    http_status="$(curl -sS -o "$tmp_body" -w "%{http_code}" \
        -X POST "${API_BASE}/api/v1/dataset-groups/register-classification" \
        -H "Content-Type: application/json" \
        --data "$payload")"
    response_body="$(cat "$tmp_body")"
    rm -f "$tmp_body"

    if [[ "$http_status" != "200" && "$http_status" != "201" && "$http_status" != "202" ]]; then
        log_error "등록 실패: $group_name $split (HTTP $http_status)"
        log_error "응답: $response_body"
        return 1
    fi

    local returned_group_id
    returned_group_id="$(echo "$response_body" | jq -r '.group_id // empty')"
    [[ -n "$returned_group_id" ]] || { log_error "응답에서 group_id 추출 실패: $response_body"; return 1; }

    log_ok "등록 접수: $group_name $split → group_id=$returned_group_id"
    echo "$returned_group_id"
}

# ---------------------------------------------------------------------------
# YOLO 라벨 .txt 목록을 호스트 절대경로 배열로 채워주는 헬퍼.
# 결과는 전역 배열 YOLO_LABEL_FILES 에 들어간다 (bash 함수의 반환값 한계 때문).
# ---------------------------------------------------------------------------
collect_yolo_label_files() {
    local labels_dir="$1"
    YOLO_LABEL_FILES=()
    while IFS= read -r -d '' txt_path; do
        YOLO_LABEL_FILES+=("$txt_path")
    done < <(find "$labels_dir" -maxdepth 1 -type f -name '*.txt' -print0 | sort -z)
    [[ ${#YOLO_LABEL_FILES[@]} -gt 0 ]] || die "라벨 .txt 가 없습니다: $labels_dir"
}

# ---------------------------------------------------------------------------
# Classification head 스펙 빌더
#
# 사용법:
#   build_head_spec <head_name> <multi_label_bool> <host_class_path1>:<class_name1>
#                                                  <host_class_path2>:<class_name2> ...
# 표준출력으로 단일 head JSON 객체를 출력한다.
# ---------------------------------------------------------------------------
build_head_spec() {
    local head_name="$1"
    local multi_label="$2"
    shift 2

    local class_names_json='[]'
    local source_class_paths_json='[]'
    local pair host_path class_name container_path

    for pair in "$@"; do
        host_path="${pair%%::*}"
        class_name="${pair##*::}"
        assert_exists_dir "$host_path"
        container_path="$(to_container_path "$host_path")"
        class_names_json="$(echo "$class_names_json" | jq --arg c "$class_name" '. + [$c]')"
        source_class_paths_json="$(echo "$source_class_paths_json" | jq --arg p "$container_path" '. + [$p]')"
    done

    jq -n \
        --arg name "$head_name" \
        --argjson multi_label "$multi_label" \
        --argjson classes "$class_names_json" \
        --argjson source_class_paths "$source_class_paths_json" \
        '{
            name: $name,
            multi_label: $multi_label,
            classes: $classes,
            source_class_paths: $source_class_paths
        }'
}

# ===========================================================================
# 1) coco2017 (RAW / COCO / DETECTION)
#    TRAIN 1.0  : images/train2017 + annotations/instances_train2017.json (449M)
#    VAL   1.0  : images/val2017   + annotations/instances_val2017.json
#
#  주의: 현재 DB 에서 TRAIN 1.0 은 status=PROCESSING, annotation_files=null 로
#        반쯤 등록된 상태. 본 스크립트는 정상 등록을 다시 시도한다.
#        train2017 어노테이션 JSON 이 매우 커 (~450MB) Celery 단계에서 시간이
#        오래 걸릴 수 있다.
# ===========================================================================
log_info "=========================================================="
log_info " 1) coco2017 (COCO / DETECTION)"
log_info "=========================================================="
COCO2017_BASE="${HOST_UPLOAD_BASE}/coco_dataset"

coco2017_group_id="$(
    register_detection "coco2017" "" "TRAIN" "COCO" "DETECTION" \
        "${COCO2017_BASE}/images/train2017" \
        "" \
        "${COCO2017_BASE}/annotations/instances_train2017.json"
)"

register_detection "coco2017" "$coco2017_group_id" "VAL" "COCO" "DETECTION" \
    "${COCO2017_BASE}/images/val2017" \
    "" \
    "${COCO2017_BASE}/annotations/instances_val2017.json" >/dev/null

# ===========================================================================
# 2) coco8_yolo (RAW / YOLO / DETECTION)
#    TRAIN 1.0, TRAIN 2.0  : images/train + labels/train/*.txt
#    VAL   1.0             : images/val   + labels/val/*.txt
#    YOLO data.yaml 은 source_annotation_meta_file 로 전달 (클래스 매핑)
# ===========================================================================
log_info "=========================================================="
log_info " 2) coco8_yolo (YOLO / DETECTION)"
log_info "=========================================================="
COCO8_BASE="${HOST_UPLOAD_BASE}/coco8"
COCO8_YAML="${COCO8_BASE}/coco8.yaml"

# TRAIN 1.0 — 신규 그룹 생성
collect_yolo_label_files "${COCO8_BASE}/labels/train"
coco8_group_id="$(
    register_detection "coco8_yolo" "" "TRAIN" "YOLO" "DETECTION" \
        "${COCO8_BASE}/images/train" \
        "$COCO8_YAML" \
        "${YOLO_LABEL_FILES[@]}"
)"

# TRAIN 2.0 — 같은 그룹/같은 split 에 다시 등록하면 자동으로 2.0 이 부여됨
collect_yolo_label_files "${COCO8_BASE}/labels/train"
register_detection "coco8_yolo" "$coco8_group_id" "TRAIN" "YOLO" "DETECTION" \
    "${COCO8_BASE}/images/train" \
    "$COCO8_YAML" \
    "${YOLO_LABEL_FILES[@]}" >/dev/null

# VAL 1.0
collect_yolo_label_files "${COCO8_BASE}/labels/val"
register_detection "coco8_yolo" "$coco8_group_id" "VAL" "YOLO" "DETECTION" \
    "${COCO8_BASE}/images/val" \
    "$COCO8_YAML" \
    "${YOLO_LABEL_FILES[@]}" >/dev/null

# ===========================================================================
# 3) coco128_yolo (RAW / YOLO / DETECTION)
#    TRAIN 1.0 만 존재. images/train2017 + labels/train2017/*.txt
# ===========================================================================
log_info "=========================================================="
log_info " 3) coco128_yolo (YOLO / DETECTION)"
log_info "=========================================================="
COCO128_BASE="${HOST_UPLOAD_BASE}/coco128"
COCO128_YAML="${COCO128_BASE}/coco128.yaml"

collect_yolo_label_files "${COCO128_BASE}/labels/train2017"
register_detection "coco128_yolo" "" "TRAIN" "YOLO" "DETECTION" \
    "${COCO128_BASE}/images/train2017" \
    "$COCO128_YAML" \
    "${YOLO_LABEL_FILES[@]}" >/dev/null

# ===========================================================================
# 4) hardhat_orig (RAW / CLS_MANIFEST / CLASSIFICATION)
#    head_schema:
#      hardhat_wear : [0_no_helmet, 1_helmet]   (single-label)
#      visibility   : [0_unseen,    1_seen]     (single-label)
#    원본 폴더 구조: hardhat_original/{train,val,test}/<head>/<class>/*.jpg
# ===========================================================================
log_info "=========================================================="
log_info " 4) hardhat_orig (CLS_MANIFEST / CLASSIFICATION)"
log_info "=========================================================="
HARDHAT_ORIG_BASE="${HOST_UPLOAD_BASE}/hardhat-dataplatform-raw/hardhat_original"

build_hardhat_orig_heads_for_split() {
    local split_dir="$1"
    local heads_json='[]'
    local head_obj

    head_obj="$(build_head_spec "hardhat_wear" false \
        "${split_dir}/hardhat_wear/0_no_helmet::0_no_helmet" \
        "${split_dir}/hardhat_wear/1_helmet::1_helmet" \
    )"
    heads_json="$(echo "$heads_json" | jq --argjson h "$head_obj" '. + [$h]')"

    head_obj="$(build_head_spec "visibility" false \
        "${split_dir}/visibility/0_unseen::0_unseen" \
        "${split_dir}/visibility/1_seen::1_seen" \
    )"
    heads_json="$(echo "$heads_json" | jq --argjson h "$head_obj" '. + [$h]')"

    echo "$heads_json"
}

# TRAIN 1.0 — 신규 그룹
hardhat_orig_train_heads="$(build_hardhat_orig_heads_for_split "${HARDHAT_ORIG_BASE}/train")"
hardhat_orig_group_id="$(
    register_classification "hardhat_orig" "" "TRAIN" \
        "${HARDHAT_ORIG_BASE}/train" \
        "$hardhat_orig_train_heads"
)"

# VAL 1.0
hardhat_orig_val_heads="$(build_hardhat_orig_heads_for_split "${HARDHAT_ORIG_BASE}/val")"
register_classification "hardhat_orig" "$hardhat_orig_group_id" "VAL" \
    "${HARDHAT_ORIG_BASE}/val" \
    "$hardhat_orig_val_heads" >/dev/null

# TEST 1.0
hardhat_orig_test_heads="$(build_hardhat_orig_heads_for_split "${HARDHAT_ORIG_BASE}/test")"
register_classification "hardhat_orig" "$hardhat_orig_group_id" "TEST" \
    "${HARDHAT_ORIG_BASE}/test" \
    "$hardhat_orig_test_heads" >/dev/null

# ===========================================================================
# 5) hardhat_headcrop (RAW / CLS_MANIFEST / CLASSIFICATION)
#    head_schema:
#      hardhat_wear : [0_no_helmet, 1_helmet]   (single-label, 한 head 만)
#    원본 폴더 구조: hardhat_headcrop/{train,val,test}/hardhat_wear/<class>/*.jpg
# ===========================================================================
log_info "=========================================================="
log_info " 5) hardhat_headcrop (CLS_MANIFEST / CLASSIFICATION)"
log_info "=========================================================="
HARDHAT_HEADCROP_BASE="${HOST_UPLOAD_BASE}/hardhat-dataplatform-raw/hardhat_headcrop"

build_hardhat_headcrop_heads_for_split() {
    local split_dir="$1"
    local heads_json='[]'
    local head_obj

    head_obj="$(build_head_spec "hardhat_wear" false \
        "${split_dir}/hardhat_wear/0_no_helmet::0_no_helmet" \
        "${split_dir}/hardhat_wear/1_helmet::1_helmet" \
    )"
    heads_json="$(echo "$heads_json" | jq --argjson h "$head_obj" '. + [$h]')"

    echo "$heads_json"
}

# TRAIN 1.0 — 신규 그룹
hardhat_headcrop_train_heads="$(build_hardhat_headcrop_heads_for_split "${HARDHAT_HEADCROP_BASE}/train")"
hardhat_headcrop_group_id="$(
    register_classification "hardhat_headcrop" "" "TRAIN" \
        "${HARDHAT_HEADCROP_BASE}/train" \
        "$hardhat_headcrop_train_heads"
)"

# VAL 1.0
hardhat_headcrop_val_heads="$(build_hardhat_headcrop_heads_for_split "${HARDHAT_HEADCROP_BASE}/val")"
register_classification "hardhat_headcrop" "$hardhat_headcrop_group_id" "VAL" \
    "${HARDHAT_HEADCROP_BASE}/val" \
    "$hardhat_headcrop_val_heads" >/dev/null

# TEST 1.0
hardhat_headcrop_test_heads="$(build_hardhat_headcrop_heads_for_split "${HARDHAT_HEADCROP_BASE}/test")"
register_classification "hardhat_headcrop" "$hardhat_headcrop_group_id" "TEST" \
    "${HARDHAT_HEADCROP_BASE}/test" \
    "$hardhat_headcrop_test_heads" >/dev/null

# ---------------------------------------------------------------------------
# 종료
# ---------------------------------------------------------------------------
log_info "=========================================================="
log_ok   " 모든 등록 요청을 접수했습니다."
log_info " 실제 파일 복사·인덱싱은 Celery worker 에서 비동기로 진행됩니다."
log_info " 상태 확인:  curl -s ${API_BASE}/api/v1/dataset-groups | jq ."
log_info "=========================================================="
