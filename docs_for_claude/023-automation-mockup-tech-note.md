# 자동화 도입 기술 검토 노트 — Step 1 파이프라인 자동화 + Step 2 학습 자동화 공통 고려

> 최초 작성: 2026-04-21
> 브랜치: `feature/pipeline-automation-mockup`
> 상위 설계서: `objective_n_plan_7th.md` v7.7 §5 item 16 / item 19~20
> 직전 핸드오프: `docs_for_claude/022-classification-dag-chapter-closure-handoff.md` §6-1

---

## 0. 이 문서의 목적

Step 1 자동화(데이터 파이프라인 자동 재실행) 실구현에 앞서, **Airflow / MLflow 같은 외부
파이프라인·실험 관리 도구를 지금 시점에 도입해야 하는가** 를 결정하기 위한 기술 검토.

핵심 판단 근거: **Step 2 학습 자동화에서 "자동화" 가 다시 등장한다.** 지금 자체 구현해 두면
Step 2 에서 같은 결정을 한 번 더 해야 하고, 반대로 지금 Airflow 를 들이면 Step 2 학습 특유의
요구 (GPU 스케줄링, 실험 추적) 까지 같은 도구로 덮을 수 있을지 확인해야 한다.

결론부터 요약하면 **"지금은 도입하지 않는다"** 가 권고이며, 근거는 §5 에 정리한다.

---

## 1. 자동화가 등장하는 두 지점

### 1-1. Step 1 — 데이터 파이프라인 자동화 (§6-1, 2026-04-21 사용자 확정 모델)

**전제.** 사용자가 파이프라인을 최초 1회 수동 실행해 동작을 검증한 뒤, 해당 파이프라인을
automation 대상으로 등록한다. 등록 자체는 실행을 트리거하지 않는다.

**동작 모델 (사용자 확정 · 2026-04-21).**

1. **등록 단위 = 파이프라인**: 파이프라인별 automation 상태 (`stopped` / `active` / `error`)
   를 가진다. 기본 `stopped`.
2. **활성 모드 (파이프라인별 선택)**
   - **polling (lazy)**: 파이프라인별 개별 주기로 "input 최신 버전 vs 마지막 자동 실행 시 사용한
     버전" 을 주기 스캔. delta 가 있으면 실행.
   - **triggering (즉시)**: input DatasetGroup 에 새 버전이 commit 되는 순간 즉시 실행. 주기
     설정 없음.
3. **수동 재실행 (모드 공통)**: "데이터는 이미 갱신됐는데 polling 주기가 아직 남은" 경우를
   위해, 사용자가 버튼 클릭으로 "지금 즉시 delta 검사 → delta 있으면 실행" 을 강제한다.
   triggering 모드에서도 동일 버튼 제공 (이벤트 유실 대비 안전망).
4. **Chaining 자동 분석**: 시스템이 등록된 파이프라인들의 input / output DatasetGroup 을 비교해
   파이프라인 간 의존 DAG 를 자동 구성. 예: 파이프라인 A 의 출력 그룹이 파이프라인 B 의 입력
   그룹이면 `A → B` 엣지. 사용자가 직접 체인을 그리지 않는다.
5. **사이클 감지 → `error` 상태 전환**: 자동 분석 결과 순환 (A↔B 또는 더 긴 순환) 이 형성되면
   해당 파이프라인(들) 의 `automation_status` 를 `error` 로 전환하고 사유를 기록
   (`CYCLE_DETECTED`). `error` 상태에서는 polling / triggering / 수동 재실행 모두 동작하지 않으며,
   사용자가 파이프라인 설정을 수정하거나 한쪽을 `stopped` 로 내리면 해제된다.
6. **토폴로지컬 실행**: 한 번의 검사 (polling tick / triggering event / 수동 재실행) 에서 실행
   대상으로 수집된 파이프라인 집합을 chaining DAG 의 토폴로지 순서로 정렬해 한 번에 실행.
   중복 실행 / 잘못된 순서로 인한 재실행 방지.
7. **최초 activate 동작**: `active` 로 전환해도 즉시 실행하지 않는다. 다음 polling tick / 다음
   triggering event / 수동 재실행 시점에 "마지막 자동 실행 버전 vs 현재 최신" 을 비교해 delta
   가 있을 때만 실행. → activate 후에도 input 갱신이 없으면 영원히 돌지 않을 수 있음 (의도된
   동작).
8. **실패 처리**: 연쇄 실행 중 한 파이프라인이 실패하면 **해당 파이프라인의 downstream 만 skip**.
   형제 체인 (공통 조상이지만 다른 가지) 은 계속 실행.
9. **재시도**: v1 에서는 **없음**. polling 모드는 다음 주기에서 자연 재시도되고, triggering /
   수동 재실행은 사용자가 다시 트리거할 수 있다.

**토폴로지컬 실행이 필요한 이유 (사용자 제시 예시).** 실제 의존이 `P1 → P2 → P3` 인 상태에서
아무 순서로 `P1 → P3 → P2` 를 돌리면, P2 가 실행된 뒤 P3 의 input 이 다시 바뀌어 P3 을 한 번
더 돌려야 한다. 토폴로지 순서로 한 번에 실행하면 각 파이프라인이 정확히 1회씩만 실행된다.

**성격 요약.** **파이프라인별 polling + triggering 혼재 + 수동 재실행 보조 + 토폴로지 batch 실행**.
- polling: 이벤트 유실 위험 0, 평균 레이턴시 ≈ 주기/2
- triggering: 평균 레이턴시 ≈ 0 이지만 이벤트 발행 경로가 확실해야 함 (SQLAlchemy 리스너 /
  신규 Dataset commit 훅 등)
- 수동 재실행: polling 의 대기 시간 단축 + triggering 의 유실 복구 — 두 모드의 각 약점을 상쇄

### 1-2. Step 2 — 모델 학습 자동화 (설계서 §5 item 19~20)

**진입 전제.** DockerTrainingExecutor, nvidia-smi 기반 GPUResourceManager, MLflow, Prometheus+DCGM,
SMTP 알림, `loss_per_head` 실장 (§6-2).

**자동화 요구의 갈래.**
- (a) **실험 추적**: 학습 run 별 config / metric / 모델 아티팩트 / 재현용 데이터셋 버전 기록
- (b) **자원 스케줄링**: GPU 슬롯 경합, 큐 관리 (단일 GPU 서버 → Step 3 K8S 클러스터)
- (c) **주기 학습**: 신규 데이터 누적 시 자동 재학습, Offline Testing, Auto Deploy (Step 4)

Step 2 범위는 (a) + (b) 만. (c) 는 Step 4 MLOps 진입 시.

**성격 요약.**
- (a) 는 **record-keeping** — 한 번에 한 run 을 기록하는 read-append 중심. 외부 UI (MLflow UI) 로
  브라우징하는 것이 표준.
- (b) 는 **scheduling** — 단일 GPU 서버 단계에서는 "동시에 못 돌리므로 큐" 수준. Step 3 에서
  본격 스케줄러 (Volcano / Kubeflow / Argo + KEDA) 가 필요해진다.
- (c) 는 **event-driven + schedule-driven 혼합** — §1-1 과 같은 체인 재실행 로직 + cron.

---

## 2. 현 인프라로 가능한 것 / 아닌 것

### 2-1. 가능한 것 (이미 있음)

- **DAG 실행**: `lib/pipeline/dag_executor.py` 가 topological 실행 + Phase A/B 분리 + processing.log
  까지 완비. Airflow 의 DAG 실행 레이어 역할을 이미 수행 중.
- **비동기 큐**: Celery (PostgreSQL broker) + 3개 queue (pipeline / eda / default). worker
  concurrency 4 로 동시 실행 4건까지.
- **Lineage 그래프**: `DatasetLineage` 테이블이 parent→child 엣지를 보존. BFS/CTE 로 downstream
  전수 조회 가능.
- **실행 이력**: `PipelineExecution` 에 started_at / finished_at / status / error / transform_config
  스냅샷 보존.

### 2-2. 추가 구현이 필요한 것 (Step 1 자동화 실구현의 실체)

**DB 모델 (실구현 시점에 추가).**
- `Pipeline.automation_status: str` — `"stopped"` (기본) / `"active"` / `"error"`.
- `Pipeline.automation_mode: str | None` — `"polling"` / `"triggering"`. `stopped` 일 때 null.
- `Pipeline.automation_poll_interval: str | None` — polling 모드에서만 값 (preset: `10m` / `1h`
  / `6h` / `24h`). triggering 에서는 null.
- `Pipeline.automation_error_reason: str | None` — `error` 상태 사유 (예: `CYCLE_DETECTED`,
  `INPUT_GROUP_NOT_FOUND`). `stopped` / `active` 에서는 null.
- `Pipeline.automation_last_seen_input_versions: JSONB` — `{group_id: version}` 매핑. 자동 실행
  성공 시 그 실행이 실제로 쓴 입력 버전으로 갱신. delta 검사의 기준점.
- `PipelineExecution.trigger_kind: str` — `"manual"` / `"automation"`.
- `PipelineExecution.automation_trigger_source: str | None` — automation 한정 상세: `"polling"` /
  `"triggering"` / `"manual_rerun"`.
- `PipelineExecution.automation_batch_id: UUID | None` — 같은 검사 사이클에서 토폴로지 순서로
  함께 실행된 파이프라인 그룹 ID.

**로직 컴포넌트.**
- **Chaining 분석기** (순수 함수): 등록된 (stopped 아님 + active / error) 파이프라인들의
  `PipelineConfig.output.dataset_group_id` 와 각 파이프라인 `SourceConfig.dataset_group_id`
  (input) 를 비교해 파이프라인 간 in-memory DAG 구성. DB → dict → edges 반환. 사이클 검출
  결과는 해당 파이프라인들의 `automation_status = error` / `error_reason = "CYCLE_DETECTED"`
  로 반영.
- **Polling 스캐너**: Celery beat 로 주기 실행 (각 파이프라인의 개별 주기를 beat schedule 로
  등록). `active + mode=polling` 파이프라인을 대상으로 "현재 input 최신 버전 vs
  `automation_last_seen_input_versions`" 비교해 실행 대상 수집.
- **Triggering 훅**: 신규 Dataset commit (SQLAlchemy `after_flush` 또는 별도 도메인 이벤트) 시점에
  해당 DatasetGroup 을 input 으로 삼는 `active + mode=triggering` 파이프라인 전수를 즉시 실행
  후보로 수집.
- **수동 재실행 엔드포인트**: `POST /pipelines/{id}/automation/rerun` — 요청 시점에 해당
  파이프라인 1건에 대해 delta 검사 → delta 있으면 실행. mode 와 무관하게 호출 가능.
- **실행 디스패처**: polling / triggering / 수동 재실행이 수집한 파이프라인 집합을 chaining
  DAG 의 토폴로지 순서로 정렬 → 순서대로 Celery enqueue. 한 `automation_batch_id` 로 묶어 이력
  추적. 각 파이프라인 성공 시 `automation_last_seen_input_versions` 갱신.
- **minor 버전 자동 증가**: `dataset_service._resolve_next_version` 에 `trigger_kind` 인자 추가.
  manual → major++, automation → minor++.
- **실패 처리 (v1)**: 실패 시 해당 batch 내 **해당 파이프라인의 downstream 만 skip**, 형제 체인은
  계속. 재시도 없음.

**규모 감각.** 위 전체가 Python 수백 줄 + Alembic 1~2건 수준. 외부 orchestrator 의존 없이 구현
가능 — §5 결론의 근거.

### 2-3. 규모 감각

- 현재 파이프라인 수: 수십 건 단위
- RAW 업데이트 빈도: 하루 수 건 (수동 업로드)
- 한 파이프라인 실행 시간: 수 분 ~ 수십 분 (Phase B 이미지 실체화 병목)
- 동시 실행 제약: Celery worker 4 슬롯

이 규모에서 Airflow scheduler + executor + webserver 를 띄우는 오버헤드는 ROI 가 낮다.

---

## 3. 후보 외부 도구 비교

### 3-1. Airflow

**강점.** 성숙한 DAG 정의 + 스케줄러 + Web UI (DAG 그래프, run 이력, retry 버튼). 커뮤니티 / 통합
생태계가 가장 크다.

**약점 — 우리 맥락.**
- DAG 정의가 **Python 파일 (DSL)** 기반. 우리는 이미 **JSON PipelineConfig + React Flow 에디터** 로
  DAG 를 정의·실행하고 있어 정의 레이어가 **이중화**된다.
- Airflow scheduler 는 **cron 중심**. 우리 Step 1 자동화는 event-driven 이라 `Sensor` / 외부
  Trigger API 로 우회해야 하는데, 그 지점은 결국 우리 코드가 다시 쓴다.
- 운영 컴포넌트: scheduler + webserver + metadata DB + executor(+worker). 현재 모노레포
  도커 컴포즈 4개 서비스에서 최소 2~3개 서비스가 추가된다.
- **두 개의 DAG 실행기 공존.** Airflow 의 BashOperator / PythonOperator 로 우리 Celery 태스크를
  호출하면 DAG 는 Airflow, 실제 실행은 Celery — 디버깅 경로가 두 배가 된다.

**결론.** 현재 인프라로 이미 할 수 있는 일 (DAG 실행) 을 대체하면서 부가가치가 적고, event-driven
영역에서는 오히려 번거롭다. **도입 비권장.**

### 3-2. MLflow

**강점.** 실험 추적 (params / metrics / artifacts) + 모델 레지스트리 + 간단한 추적 서버. Python
API 만으로 `with mlflow.start_run():` 패턴이라 침습성 낮음.

**약점 — 우리 맥락.**
- Step 1 (데이터 파이프라인) 에는 **맞지 않는다**. MLflow 는 학습 run 단위 기록이 목적이고,
  파이프라인 실행 이력은 이미 `PipelineExecution` 테이블로 충분히 구조화되어 있다.
- 파이프라인 실행을 MLflow run 으로도 중복 기록하면 "어느 쪽이 SSOT 냐" 가 애매해진다.

**결론.**
- **Step 1 자동화에는 도입하지 않는다** — 중복 이력 저장소.
- **Step 2 학습 자동화 진입 시에는 강력 후보.** 설계서 §5 item 20 에 이미 "MLflow" 가 명시되어
  있음. 그 시점에 실제로 도입 여부를 검증.
- 즉 MLflow 는 **지금 결정할 문제가 아님.**

### 3-3. Argo Workflows / Kubeflow Pipelines (참고)

**강점.** K8S 네이티브 DAG 실행. GPU 스케줄링·분산 학습과 직접 결합.

**약점 — 우리 맥락.**
- 전제가 K8S. 현재는 도커 컴포즈 환경이며 K8S 진입은 **Step 3** 에서 예정 (§5 item 21).
- 지금 도입하면 Step 3 까지 도입-중단 상태가 유지된다.

**결론.** Step 3 진입 시 재검토. 현재는 기록만 남김.

### 3-4. Prefect / Dagster (대안 참고)

요구가 정말로 외부 오케스트레이터를 필요로 하는 시점에는 Airflow 대신 Prefect / Dagster 도
고려 가치가 있다 — 둘 다 event-driven 이 일급 시민이고 Airflow 보다 Python 친화적. 다만 §2-2 수준의
자동화 요구에는 역시 과잉.

---

## 4. 두 자동화 도메인의 성격 비교

| 차원 | Step 1 데이터 파이프라인 | Step 2 학습 |
|---|---|---|
| 트리거 | 상류 그룹 신규 버전 (polling delta) | 사용자 제출 + 큐 (요청) + Step 4 에서 event |
| 핵심 상태 | Dataset · Lineage · PipelineExecution | TrainingRun · ModelArtifact · Metrics |
| 재현 | `transform_config` 스냅샷 | config + 데이터셋 버전 + seed |
| 결과물 | 새 Dataset 행 + 파일 | 모델 가중치 + 지표 |
| 실행 단위 | Celery 태스크 1건 = 파이프라인 1회 | Docker 컨테이너 1개 = run 1회 (Step 2) → K8S Pod (Step 3) |
| 병목 | 디스크 I/O (Phase B) | GPU 시간 |
| 이력 UI 요구 | 연쇄 트리 시각화 | 실험 비교·지표 곡선 |

**핵심 차이.** 두 자동화는 **겹치는 것처럼 보이지만 실제로 요구 컴포넌트가 다르다.**

- Step 1 에 필요한 건 **lineage + 이벤트 트리거 + Celery 큐** — 현 인프라로 90% 커버.
- Step 2 에 필요한 건 **실험 추적 + GPU 스케줄링** — 현 인프라로 거의 0% 커버.

따라서 **"지금 외부 도구 하나로 둘 다 덮는다"** 는 매력적이지만 실현되지 않는다. 한 도구가
양쪽을 잘 하는 케이스가 없다 (Airflow 는 스케줄링 잘하지만 실험 추적 없음 / MLflow 는 실험 추적
잘하지만 DAG 오케스트레이션 없음).

---

## 5. 추천

**지금 외부 도구를 도입하지 않는다.** 근거를 다음 순서로 요약.

1. **Step 1 자동화 실구현에 필요한 것은 §2-2 의 DB 모델 5개 + 로직 컴포넌트 5개** — 전부 현
   인프라 확장으로 해결 가능. Celery + Celery beat + DAG executor 가 이미 있다.
2. **Airflow 는 DAG 정의 이중화를 초래** — 우리는 JSON PipelineConfig + React Flow 에디터가
   SSOT. Airflow 의 Python DAG 가 또 하나의 SSOT 가 되면 정합성 비용이 크다.
3. **MLflow 는 Step 1 이 아니라 Step 2 의 과제** — 지금 도입하면 파이프라인 실행 이력과 이중
   기록되어 SSOT 가 흐려진다. 학습 자동화 진입 시 재검토.
4. **GPU 스케줄러 (Volcano / KEDA / Argo) 는 Step 3** — K8S 전제가 맞춰진 다음 검토.

**도입 기준 (언제가 되면 재검토하는가).**

- Step 1: 파이프라인 수가 **수백 건** 을 넘어가거나 자동화 실행이 **시간당 수십 회** 가 되면
  외부 스케줄러 ROI 재검토. 현 규모의 10배 이상 시점.
- Step 2: 학습 run 수가 쌓여 자체 실험 UI 를 만들 부담이 커지는 시점에 MLflow 도입.
- Step 3: K8S 클러스터화 완료 직후 Argo / Kubeflow 비교.

**이번 목업 브랜치에서 만들 것 (스코프 한정).**

§6 에 구체화. 핵심은 **목업 = UI + 데이터 모델 스케치** 이며 실제 자동 실행 로직은 아직 붙이지
않는다.

---

## 6. 목업 스코프 (사용자 확정 모델 반영)

> 2026-04-21 사용자 확정 automation 모델 (§1-1) 을 반영. 사용자 최종 확인 후 구현 착수.

### 6-1. 데이터 모델 스케치 (목업은 ORM 추가 없이 프론트 mock / 임시 응답으로 표현)

- **Pipeline 레벨**
  - `automation_status: "stopped" | "active" | "error"` — 기본 `stopped`
  - `automation_mode: "polling" | "triggering" | null` — `stopped` 일 때 null
  - `automation_poll_interval: "10m" | "1h" | "6h" | "24h" | null` — polling 전용
  - `automation_error_reason: string | null` — 예: `"CYCLE_DETECTED"`
  - `automation_last_seen_input_versions: dict[group_id → version]` — 표시 전용
- **PipelineExecution 레벨**
  - `trigger_kind: "manual" | "automation"`
  - `automation_trigger_source: "polling" | "triggering" | "manual_rerun" | null`
  - `automation_batch_id: UUID | null`
  - `pipeline_name: str` — UUID 대체 표시명

### 6-2. 새 화면 — Automation 관리 페이지

**목적.** 등록된 파이프라인의 automation 상태와 자동 분석된 chaining DAG 를 한 화면에서 본다.

**구성.**
- 좌: 파이프라인 목록
  - 필드: 파이프라인명 · 상태 배지 (`stopped` 회색 / `active` 초록 / `error` 빨강) · 모드
    (polling / triggering) · 주기 (polling 일 때만) · 마지막 자동 실행 시각 · 다음 예정 시각
    (polling 일 때만) · 수동 재실행 버튼
  - 상태가 `error` 인 행은 사유 텍스트 인라인 표시 (예: "사이클 감지됨 — A ↔ B")
  - 필터: 상태 · 모드 · 주기
  - 정렬: 파이프라인명 · 최근 실행 시각 · 주기
  - 행 클릭 → 해당 파이프라인 상세 Automation 탭으로 이동
- 우: 자동 분석된 chaining DAG 시각화 (React Flow 재사용)
  - 노드 = 파이프라인, 엣지 = output→input 매칭
  - 노드 색상: `stopped` 회색 / `active` 색상 / `error` 빨강
  - 사이클 감지 시 해당 엣지 빨강 + 관련 노드 빨강 강조 (목업에서는 고정 케이스 1건 시연)

### 6-3. 실행 이력 페이지 개편

- 필터: `trigger_kind` (manual / automation 복수) · `automation_trigger_source` (polling /
  triggering / manual_rerun) · 기간 · 상태 · 파이프라인
- 정렬: 시작 시각 · 파이프라인명 · 상태 · 소요 시간
- **파이프라인명 가독성 개선** — UUID 대신 `pipeline_name` 노출
- **automation batch 시각화** — 같은 `automation_batch_id` 는 트리 / 그룹으로 접힘, 펼치면
  토폴로지 순서대로 실행된 체인이 보임. batch 내 skip 된 downstream 은 "skipped" 배지
- 컬럼: 파이프라인명 · trigger_kind · source (polling/triggering/manual_rerun) · 트리거된 입력
  버전 · 상태 · 시작 시각 · 소요 · 결과 Dataset

### 6-4. 파이프라인 상세 페이지에 Automation 탭 추가

- 상태 배지 + 현재 설정 요약 (mode / interval / 마지막 실행)
- 설정 폼:
  - Status 전환 버튼: `stopped` ↔ `active` (`error` 는 사용자가 직접 들어가지 않음, 시스템
    자동 전환)
  - Mode 라디오: polling / triggering
  - Poll interval 드롭다운 (polling 일 때만 활성)
  - **수동 재실행 버튼**: 요청 시 즉시 delta 검사 → delta 있으면 실행, 없으면 안내 토스트.
    `error` 상태에서는 비활성
- 상류 DatasetGroup 목록 — 각 그룹의 현재 최신 버전 / 자동 처리 기준 버전 (delta 이면
  "새 버전 감지됨" 표시)
- 최근 automation 실행 N 건 요약 (source 별 필터)
- `error` 상태이면 사유 + 사용자 해결 가이드 표시 (예: "사이클 감지됨: A → B → A. A 또는 B 중
  하나를 stopped 로 변경하세요")

### 6-5. 만들지 않는 것 (명시적 out-of-scope)

- Celery beat 폴링 스캐너 실제 구현
- Triggering 훅 (SQLAlchemy 리스너 / 도메인 이벤트) 실제 구현
- Chaining 분석기 실제 구현 (프론트 mock 데이터로 DAG 렌더링)
- `automation_last_seen_input_versions` 실제 갱신 로직
- 수동 재실행 endpoint 실제 실행 (버튼은 mock 응답)
- minor 버전 자동 증가 실제 분기
- 실패 시 downstream skip 실제 분기
- DB 스키마 변경 — 목업 단계에서는 Alembic 건들지 않는다

**목업 수용 기준.** §6-2 ~ §6-4 의 세 화면이 mock 데이터로 렌더링되고, 필터 / 정렬 / 상태
배지 / 모드 전환 / 수동 재실행 버튼 클릭 → mock 응답 UX 가 동작하면 완료. 실제 자동 실행은
후속 챕터.

---

## 7. 목업 진입 전 결정 필요 사항 (세션 종료 시점 · 2026-04-21)

목업 UI 구현을 시작하기 전에 사용자 확인이 필요한 항목. 이 브랜치는 classification DAG
버그 수정을 위해 일시 중단되었으며, 재개 시 아래 항목부터 정리한 뒤 화면 구현에 진입한다.

### 7-1. Mock 데이터 전략 (블로킹)

UI 목업을 렌더링할 데이터 소스를 어떻게 마련할지 결정 필요. 선택지:

- **A. 프론트 상수 하드코딩** — `frontend/src/mocks/automation.ts` 에 샘플 파이프라인 5~6 건 +
  chaining + 실행 이력 fixture. 백엔드 전혀 안 건드림. 가장 빠름. **추천.**
- **B. 임시 API endpoint** — 백엔드에 `GET /api/v1/automation/mock/*` 고정 응답 라우트 추가.
  실제 API 연결 경로 검증은 되지만 코드량 증가.
- **C. 실제 스키마 초안 + 빈 응답** — 실제 API 경로에 automation 필드 추가하되 값은 stub.
  실구현으로 이어가기 쉽지만 이후 스키마가 다시 설계되면 버려짐.

추천 근거: 목업 목적이 "UX 로 동작 모델을 검증" 이라 백엔드 왕복 없이 화면 전환 / 필터 / 토글을
빠르게 만져보는 것이 목적에 부합. 실구현 시 어차피 스키마부터 재설계.

### 7-2. Pipeline 엔티티 부재 (중요 · 모델링 결정)

**현 상태 확인.** 코드 베이스에는 `PipelineExecution` 만 존재하고 독립된 `Pipeline` 엔티티는
없다 (`backend/app/models/all_models.py:235`). 현재 "파이프라인" 은 `PipelineExecution.transform_config`
안의 `PipelineConfig` JSON 스냅샷으로만 존재하며, 같은 설정을 두 번 실행하면 별개의 두
PipelineExecution 행이 생긴다.

**Automation 이 요구하는 것.** automation 은 "**이 파이프라인** 을 자동 실행 대상으로 등록" 이라는
개념이 필요하다 — 즉 실행과 독립된 **파이프라인 template 엔티티** 가 필요하다.

**옵션.**
1. **신규 `Pipeline` 테이블 도입** — `id, name, description, config (JSONB), created_at,
   updated_at, automation_*` 컬럼. `PipelineExecution.pipeline_id FK` 로 연결. 가장 자연스러운
   모델이지만 마이그레이션 + 기존 코드 수정 필요.
2. **기존 PipelineExecution 중 하나를 "latest / template" 으로 지정** — 새 엔티티 없이 가장 최근
   실행을 template 으로 간주. 모델 변경 없지만 "이름을 실행과 다르게 관리" 같은 요구가 생기면
   흐트러짐.
3. **PipelineConfig JSON 에 uuid + name 필드 추가** — template 이 문서 안에 들어감. 외부 FK 불가.

**목업에서의 영향.** 목업 단계에서는 mock fixture 가 `Pipeline` 개념을 그냥 상정하고 그림. 단,
UI 필드 (pipeline_name 의 출처 등) 가 최종 모델 선택에 따라 달라질 수 있음. 사용자는 **구현
챕터 진입 전에 1/2/3 중 하나를 결정**해야 한다. 목업은 1 번 가정으로 진행해도 무방.

**권고.** 장기적으로는 1 번 (`Pipeline` 엔티티) 이 유일하게 확장 가능한 모델. automation 외에도
"이 파이프라인의 실행 통계", "이 파이프라인의 마지막 실행 결과", "파이프라인 즐겨찾기" 등이
전부 1 번 모델에서만 자연스럽다.

### 7-3. `pipeline_name` 필드의 출처

사용자가 파이프라인 생성 시 수동으로 입력 / 자동 생성 / 둘 다 허용. 현재 UI 에 이 필드가 있는지
불명확. 목업에서는 mock fixture 에 사람이 읽을 수 있는 이름 (`"hardhat detection v1"`,
`"wear classification train prep"` 등) 을 박고 표시만 검증.

### 7-4. UI 네비게이션에서 Automation 관리 페이지 위치

- 상단 주 네비에 "Automation" 메뉴를 추가할지
- 기존 파이프라인 관리 페이지의 서브 탭으로 둘지
- 파이프라인 실행 이력 페이지 옆에 병렬로 둘지

목업 단계에서 확정 필요.

### 7-5. 수동 재실행 버튼 UX 세부

- 클릭 시 확인 다이얼로그 여부 ("지금 즉시 delta 검사 후 실행합니다. 계속?")
- 버튼 위치: 파이프라인 목록 행별 / 파이프라인 상세 탭 내부 / 둘 다
- 실행 결과 피드백: 토스트 / 실행 이력 페이지로 자동 이동 / 모달

### 7-6. Chaining DAG 시각화에서 미실행 파이프라인 표시

등록은 됐지만 아직 한 번도 실행된 적 없는 파이프라인 (PipelineExecution 이력 0 건) 을 DAG 에
표시할지, 표시한다면 어떤 배지 / 색상으로 구분할지.

### 7-7. 수동 실행과 automation 실행의 버전 정책 일관성

설계서 §5 item 18 "버전 정책 운영 검증" 과 연결. 현재 `dataset_service._resolve_next_version` 이
major/minor 를 어떻게 결정하는지 재확인 + automation 진입 시 `trigger_kind` 를 어떻게 흘릴지
구체화. 목업 범위는 아니지만 실구현 챕터 진입 전에 명확히 해야 함.

---

## 8. 현재 상태 스냅샷 (2026-04-21 세션 종료)

- **브랜치**: `feature/pipeline-automation-mockup` (main 으로부터 fork, 커밋 없음)
- **진행**: 기술 검토 노트 v1 작성 완료. §1 ~ §6 사용자 확정 모델 반영. §7 블로킹 결정 사항
  정리.
- **중단 사유**: classification DAG 버그 수정 우선 처리.
- **재개 시 체크리스트**:
  1. §7-1 mock 데이터 전략 확정 (A / B / C 중 택)
  2. §7-2 Pipeline 엔티티 모델링 방향 확정 (목업은 1 번 가정으로도 진행 가능)
  3. §7-3 ~ §7-6 UI 세부 확정
  4. Mock fixture 설계 (§7-1 의 선택에 따라)
  5. Automation 관리 페이지 / 실행 이력 개편 / 파이프라인 상세 Automation 탭 구현 착수
