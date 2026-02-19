"""
학습 실행기 추상 인터페이스 (Phase 3 골격, 2차에서 구현)

설계:
  - 2차: DockerTrainingExecutor (단일 GPU 서버, docker run)
  - 3차: KubernetesTrainingExecutor (K8S Pod)
  구현체 교체 시 비즈니스 로직 수정 없음.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class JobStatus:
    """학습 job 상태."""
    job_id: str
    status: str          # PENDING | RUNNING | DONE | FAILED | CANCELLED
    progress: float = 0.0  # 0.0 ~ 1.0
    message: str | None = None
    metrics: dict | None = None


class TrainingExecutor(ABC):
    """
    학습 실행기 추상 인터페이스.
    2차: DockerTrainingExecutor
    3차: KubernetesTrainingExecutor
    """

    @abstractmethod
    async def submit_job(
        self,
        solution_version_id: str,
        gpu_ids: list[int],
        config: dict,
    ) -> str:
        """
        학습 job 제출.

        Args:
            solution_version_id: SolutionVersion.id
            gpu_ids: 할당된 GPU 번호 목록
            config: 학습 설정 (recipe + override 합산)

        Returns:
            job_id (container_id or pod_name)
        """
        ...

    @abstractmethod
    async def get_job_status(self, job_id: str) -> JobStatus:
        """job 상태 조회."""
        ...

    @abstractmethod
    async def cancel_job(self, job_id: str) -> bool:
        """job 취소."""
        ...

    @abstractmethod
    async def get_job_logs(self, job_id: str, tail: int = 100) -> str:
        """job 로그 조회."""
        ...


class DockerTrainingExecutor(TrainingExecutor):
    """
    Docker 기반 학습 실행기 (2차에서 구현).
    단일 GPU 서버에서 docker run으로 학습 컨테이너 실행.
    """

    async def submit_job(self, solution_version_id: str, gpu_ids: list[int], config: dict) -> str:
        raise NotImplementedError("2차에서 구현 예정")

    async def get_job_status(self, job_id: str) -> JobStatus:
        raise NotImplementedError("2차에서 구현 예정")

    async def cancel_job(self, job_id: str) -> bool:
        raise NotImplementedError("2차에서 구현 예정")

    async def get_job_logs(self, job_id: str, tail: int = 100) -> str:
        raise NotImplementedError("2차에서 구현 예정")


class KubernetesTrainingExecutor(TrainingExecutor):
    """
    K8S 기반 학습 실행기 (3차에서 구현).
    Kubeflow / Argo Workflows 연동.
    """

    async def submit_job(self, solution_version_id: str, gpu_ids: list[int], config: dict) -> str:
        raise NotImplementedError("3차에서 구현 예정")

    async def get_job_status(self, job_id: str) -> JobStatus:
        raise NotImplementedError("3차에서 구현 예정")

    async def cancel_job(self, job_id: str) -> bool:
        raise NotImplementedError("3차에서 구현 예정")

    async def get_job_logs(self, job_id: str, tail: int = 100) -> str:
        raise NotImplementedError("3차에서 구현 예정")
