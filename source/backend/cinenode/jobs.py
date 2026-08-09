from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import Any

from .config import AppConfig
from .engines import EngineExecutionError, EngineRegistry
from .events import EventBus
from .governance import log_governance
from .schemas import WorkflowGraph
from .store import Store
from .util import utc_now
from .workflow import WorkflowExecutor, WorkflowValidationError


class JobManager:
    def __init__(self, store: Store, registry: EngineRegistry, config: AppConfig, events: EventBus):
        self.store = store
        self.registry = registry
        self.config = config
        self.events = events
        self.executor = WorkflowExecutor(store, config, registry)
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None
        self._active_job_id: str | None = None
        self._stopping = False

    async def start(self) -> None:
        self.store.recover_interrupted_jobs()
        self._stopping = False
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker(), name="cinenode-job-worker")
        for job in reversed(self.store.list_jobs(limit=500)):
            if job["status"] == "QUEUED":
                await self.queue.put(job["id"])

    async def stop(self) -> None:
        self._stopping = True
        await self.queue.put(None)
        if self.worker_task:
            try:
                await asyncio.wait_for(self.worker_task, timeout=15)
            except TimeoutError:
                self.worker_task.cancel()
            self.worker_task = None

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)
        await self.events.publish("jobs.updated", {"job_id": job_id, "status": "QUEUED"})

    async def _worker(self) -> None:
        while not self._stopping:
            job_id = await self.queue.get()
            try:
                if job_id is None:
                    return
                await self._run(job_id)
            finally:
                self.queue.task_done()

    async def _run(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job["status"] != "QUEUED":
            return
        if job["cancel_requested"]:
            self.store.update_job(job_id, status="CANCELLED", progress=0.0, finished_at=utc_now())
            await self.events.publish("jobs.updated", {"job_id": job_id, "status": "CANCELLED"})
            return
        self._active_job_id = job_id
        log_path = self.config.logs_dir / f"job-{job_id}.log"
        self.store.update_job(job_id, status="RUNNING", started_at=utc_now(), error_code=None, error_message=None)
        log_governance(self.store.db, "INFO", "job.started", {"job_id": job_id})
        await self.events.publish("jobs.updated", {"job_id": job_id, "status": "RUNNING"})

        def cancelled() -> bool:
            try:
                return bool(self.store.get_job(job_id)["cancel_requested"])
            except Exception:
                return True

        async def progress(value: float, node_id: str) -> None:
            self.store.update_job(job_id, progress=max(0.0, min(100.0, float(value))), current_node_id=node_id or None)
            await self.events.publish("jobs.updated", {"job_id": job_id, "status": "RUNNING", "progress": value, "current_node_id": node_id})

        async def log(level: str, message: str) -> None:
            line = f"{utc_now()} [{level.upper()}] {message}\n"
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(line)

        try:
            graph = WorkflowGraph.model_validate(job["graph"])
            result = await self.executor.execute(
                job_id,
                job["project_id"],
                graph,
                progress=progress,
                log=log,
                cancel_check=cancelled,
            )
            payload = {
                "terminal_results": result.terminal_results,
                "assets": result.assets,
                "node_results": result.node_results,
                "log_path": str(log_path),
            }
            self.store.update_job(
                job_id,
                status="SUCCEEDED",
                progress=100.0,
                current_node_id=None,
                result_json=payload,
                finished_at=utc_now(),
            )
            log_governance(self.store.db, "INFO", "job.succeeded", {"job_id": job_id, "assets": len(result.assets)})
            await self.events.publish("jobs.updated", {"job_id": job_id, "status": "SUCCEEDED", "progress": 100})
            await self.events.publish("gallery.updated", {"job_id": job_id})
        except EngineExecutionError as exc:
            status = "CANCELLED" if exc.code == "JOB_CANCELLED" else "FAILED"
            self.store.update_job(
                job_id,
                status=status,
                error_code=exc.code,
                error_message=f"{exc.message}{(': ' + exc.detail) if exc.detail else ''}",
                finished_at=utc_now(),
                current_node_id=None,
            )
            log_governance(self.store.db, "WARN" if status == "CANCELLED" else "ERROR", f"job.{status.lower()}", {"job_id": job_id, "code": exc.code, "message": exc.message, "detail": exc.detail})
            await self.events.publish("jobs.updated", {"job_id": job_id, "status": status, "error_code": exc.code})
        except WorkflowValidationError as exc:
            self.store.update_job(job_id, status="FAILED", error_code="WORKFLOW_INVALID", error_message=str(exc.errors), finished_at=utc_now(), current_node_id=None)
            log_governance(self.store.db, "ERROR", "job.failed", {"job_id": job_id, "code": "WORKFLOW_INVALID", "errors": exc.errors})
            await self.events.publish("jobs.updated", {"job_id": job_id, "status": "FAILED", "error_code": "WORKFLOW_INVALID"})
        except BaseException as exc:
            detail = "".join(traceback.format_exception(exc))
            await log("error", detail)
            self.store.update_job(job_id, status="FAILED", error_code="UNEXPECTED_ERROR", error_message=str(exc), finished_at=utc_now(), current_node_id=None)
            log_governance(self.store.db, "ERROR", "job.failed", {"job_id": job_id, "code": "UNEXPECTED_ERROR", "message": str(exc)})
            await self.events.publish("jobs.updated", {"job_id": job_id, "status": "FAILED", "error_code": "UNEXPECTED_ERROR"})
        finally:
            self._active_job_id = None
            await self.events.publish("governance.updated", {"source": "job", "job_id": job_id})

    @property
    def active_job_id(self) -> str | None:
        return self._active_job_id
