from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import WorkflowAgent
from .backup import BackupError, create_backup, export_project, restore_backup
from .config import AppConfig
from .database import Database
from .engines import EngineExecutionError, EngineRegistry
from .events import EventBus
from .governance import log_governance, read_governance_snapshot, seed_governance, update_task
from .jobs import JobManager
from .preflight import preflight_workflow
from .schemas import (
    AgentPlanRequest,
    AgentPlanResponse,
    BackupRequest,
    GovernanceTaskPatch,
    JobCreate,
    ProjectCreate,
    ProjectUpdate,
    ProviderInvocationRequest,
    ProviderTestRequest,
    RestoreRequest,
    SettingsPatch,
    WorkflowGraph,
)
from .security import require_local_request, sanitize_filename
from .store import Store
from .util import sha256_file, utc_now
from .workflow import NODE_CATALOG, validate_workflow



def _workflow_templates() -> list[dict[str, Any]]:
    return [
        {"id": "image-multiref-4k", "label": "Imagem multirreferência 4K", "target": "image", "description": "Brief + referências tipadas + diretor IA + geração + upscale + entrega 4K."},
        {"id": "video-start-end-4k", "label": "Vídeo start/end 4K", "target": "video", "description": "Quadro inicial/final + continuidade + geração + upscale + entrega."},
        {"id": "film-3-shots-4k", "label": "Filme em 3 takes", "target": "film", "description": "Diretor IA, três takes consistentes, montagem e exportação."},
        {"id": "multiview-to-3d", "label": "Multiview para GLB", "target": "3d", "description": "Vistas front/left/right/back para mesh texturizado e turntable."},
    ]

def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig.from_env()
    config.ensure_directories()
    db = Database(config.database)
    db.initialize()
    store = Store(db, config)
    store.initialize_defaults()
    seed_governance(db)
    events = EventBus()
    registry = EngineRegistry(store, config)
    agent = WorkflowAgent(store, registry)
    jobs = JobManager(store, registry, config, events)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_governance(db, "INFO", "app.started", {"version": "0.3.0", "home": str(config.home)})
        await jobs.start()
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False
            await jobs.stop()
            log_governance(db, "INFO", "app.stopped", {})

    app = FastAPI(
        title="Avangard Visual",
        version="0.3.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.db = db
    app.state.store = store
    app.state.events = events
    app.state.registry = registry
    app.state.agent = agent
    app.state.jobs = jobs
    app.state.ready = False

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.path.startswith("/api/") or request.url.path.startswith("/media/"):
            try:
                require_local_request(request, config)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "Entrada inválida", "details": exc.errors()}})

    @app.exception_handler(BackupError)
    async def backup_error(_: Request, exc: BackupError):
        return JSONResponse(status_code=400, content={"error": {"code": "BACKUP_ERROR", "message": str(exc)}})

    @app.exception_handler(EngineExecutionError)
    async def engine_error(_: Request, exc: EngineExecutionError):
        log_governance(db, "ERROR", "engine.request_failed", {"code": exc.code, "message": exc.message, "detail": exc.detail})
        return JSONResponse(status_code=422, content={"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}})

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception):
        log_governance(db, "ERROR", "api.unhandled_error", {"type": type(exc).__name__, "message": str(exc)})
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}})

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "ready": bool(app.state.ready),
            "version": "0.3.0",
            "database": str(config.database),
            "active_job_id": jobs.active_job_id,
            "time": utc_now(),
        }

    @app.get("/api/bootstrap")
    async def bootstrap():
        settings = store.list_settings()
        return {
            "app": {"name": "Avangard Visual", "version": "0.3.0", "profile": settings.get("app.profile")},
            "preferences": settings.get("app.preferences"),
            "node_catalog": NODE_CATALOG,
            "model_profiles": settings.get("model_profiles", {}),
            "providers": registry.provider_catalog(),
            "workflow_templates": _workflow_templates(),
            "paths": {
                "home": str(config.home), "models": str(config.models_dir), "engines": str(config.engines_dir),
                "outputs": str(config.outputs_dir), "backups": str(config.backups_dir), "logs": str(config.logs_dir),
            },
        }

    @app.get("/api/projects")
    async def list_projects():
        return {"items": store.list_projects()}

    @app.post("/api/projects", status_code=201)
    async def create_project(payload: ProjectCreate):
        project = store.create_project(payload)
        await events.publish("projects.updated", {"project_id": project["id"], "action": "created"})
        return project

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        return store.get_project(project_id)

    @app.put("/api/projects/{project_id}")
    async def update_project(project_id: str, payload: ProjectUpdate):
        project = store.update_project(project_id, payload)
        await events.publish("projects.updated", {"project_id": project_id, "action": "updated"})
        return project

    @app.delete("/api/projects/{project_id}", status_code=204)
    async def delete_project(project_id: str):
        store.delete_project(project_id)
        await events.publish("projects.updated", {"project_id": project_id, "action": "deleted"})
        return None

    @app.post("/api/projects/{project_id}/export")
    async def export_project_route(project_id: str):
        return export_project(db, config, project_id)

    @app.post("/api/workflows/validate")
    async def validate_graph(graph: WorkflowGraph):
        return validate_workflow(graph, for_execution=False)

    @app.post("/api/workflows/preflight")
    async def preflight_graph(graph: WorkflowGraph):
        return await preflight_workflow(store, registry, graph)

    @app.get("/api/nodes/catalog")
    async def node_catalog():
        return {"items": NODE_CATALOG}

    @app.get("/api/workflow-templates")
    async def workflow_templates():
        return {"items": _workflow_templates()}

    @app.post("/api/agent/plan", response_model=AgentPlanResponse)
    async def agent_plan(payload: AgentPlanRequest):
        result = await agent.plan(payload)
        log_governance(db, "INFO", "agent.plan_created", {"target": payload.target, "provider": result["decisions"].get("provider"), "nodes": len(result["graph"].nodes)})
        if result.get("project"):
            await events.publish("projects.updated", {"project_id": result["project"]["id"], "action": "created_by_agent"})
        await events.publish("governance.updated", {"source": "agent"})
        return result

    @app.get("/api/providers/catalog")
    async def provider_catalog():
        return {"items": registry.provider_catalog()}

    @app.get("/api/providers/status")
    async def provider_status():
        return {"items": await registry.provider_status_all(), "checked_at": utc_now()}

    @app.post("/api/providers/test")
    async def provider_test(payload: ProviderTestRequest):
        item = next((entry for entry in await registry.provider_status_all() if entry["id"] == payload.provider_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Provider not found")
        return item

    @app.post("/api/providers/invoke")
    async def provider_invoke(payload: ProviderInvocationRequest):
        references = []
        for selection in payload.references:
            asset = store.get_asset(selection.asset_id)
            path = Path(asset["path"]).resolve()
            if not path.is_file():
                raise HTTPException(status_code=422, detail=f"Reference file missing: {path}")
            references.append({**selection.model_dump(), "path": str(path)})
        operation = payload.operation
        parameters = dict(payload.parameters)
        parameters["provider"] = payload.provider_id
        result: dict[str, Any]
        if operation == "enhance_prompt":
            text = await registry.enhance_prompt(payload.prompt, parameters)
            result = {"kind": "text", "text": text, "provider": payload.provider_id}
        elif operation == "vision":
            text = await registry.vision(payload.prompt, references, parameters)
            result = {"kind": "text", "text": text, "provider": payload.provider_id}
        else:
            extension = {"image": ".png", "image_edit": ".png", "video": ".mp4", "mesh": ".glb"}[operation]
            output_dir = config.outputs_dir / "provider-diagnostics"
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"{utc_now().replace(':', '').replace('-', '')}-{sanitize_filename(payload.provider_id)}{extension}"
            if operation in {"image", "image_edit"}:
                generated = await registry.generate_image(payload.prompt, payload.negative_prompt, output, parameters, references=references, operation=operation)
                kind = "image"
            elif operation == "video":
                generated = await registry.generate_video(payload.prompt, payload.negative_prompt, output, parameters, references=references)
                kind = "video"
            else:
                generated = await registry.generate_mesh(payload.prompt, payload.negative_prompt, references, output, parameters)
                kind = "mesh"
            actual = Path(generated["path"]).resolve()
            asset = store.add_asset(actual, kind, metadata={"source": "provider_diagnostic", "provider": payload.provider_id, "operation": operation})
            result = {"kind": kind, "path": str(actual), "asset": asset, "provider_result": generated}
            await events.publish("gallery.updated", {"asset_id": asset["id"]})
        log_governance(db, "INFO", "provider.invoked", {"provider": payload.provider_id, "operation": operation, "result_kind": result.get("kind")})
        return result

    @app.get("/api/jobs")
    async def list_jobs(limit: int = 100):
        return {"items": store.list_jobs(limit)}

    @app.post("/api/jobs", status_code=202)
    async def create_job(payload: JobCreate):
        if payload.project_id:
            project = store.get_project(payload.project_id)
            graph = payload.graph or WorkflowGraph.model_validate(project["graph"])
        elif payload.graph:
            graph = payload.graph
        else:
            raise HTTPException(status_code=400, detail="Provide project_id or graph")
        validation = validate_workflow(graph, for_execution=True)
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={"code": "WORKFLOW_INVALID", "errors": validation["errors"]})
        job = store.create_job(payload.project_id, graph)
        await jobs.enqueue(job["id"])
        return job

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        return store.get_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        job = store.request_cancel(job_id)
        await events.publish("jobs.updated", {"job_id": job_id, "cancel_requested": True})
        return job

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry_job(job_id: str):
        job = store.retry_job(job_id)
        await jobs.enqueue(job["id"])
        return job

    @app.get("/api/assets")
    async def list_assets(limit: int = 200, project_id: str | None = None):
        return {"items": store.list_assets(limit, project_id)}

    @app.post("/api/assets/upload", status_code=201)
    async def upload_asset(file: UploadFile = File(...), project_id: str | None = None):
        safe_name = sanitize_filename(file.filename or "upload.bin")
        temp_path = config.temp_dir / f"incoming-{os.getpid()}-{safe_name}.part"
        total = 0
        try:
            with temp_path.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > config.max_upload_bytes:
                        raise HTTPException(status_code=413, detail=f"Upload exceeds {config.max_upload_bytes} bytes")
                    stream.write(chunk)
            destination = config.uploads_dir / f"{utc_now().replace(':','')}-{safe_name}"
            os.replace(temp_path, destination)
            mime = file.content_type or "application/octet-stream"
            mesh_suffixes = {".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usdz"}
            kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else "mesh" if destination.suffix.lower() in mesh_suffixes else "file"
            asset = store.add_asset(destination, kind, project_id=project_id, original_name=safe_name, mime_type=mime, metadata={"uploaded": True})
            await events.publish("gallery.updated", {"asset_id": asset["id"]})
            return asset
        finally:
            await file.close()
            temp_path.unlink(missing_ok=True)

    @app.get("/api/assets/{asset_id}")
    async def get_asset(asset_id: str):
        return store.get_asset(asset_id)

    @app.get("/media/{asset_id}")
    async def serve_asset(asset_id: str):
        asset = store.get_asset(asset_id)
        path = Path(asset["path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Asset file missing")
        return FileResponse(path, media_type=asset["mime_type"], filename=asset["original_name"] or path.name)

    @app.get("/api/settings")
    async def get_settings():
        return store.list_settings()

    @app.patch("/api/settings")
    async def patch_settings(payload: SettingsPatch):
        forbidden = {"local_access_token"}
        for key, value in payload.values.items():
            if key in forbidden:
                raise HTTPException(status_code=400, detail=f"Setting cannot be changed through API: {key}")
            store.set_setting(key, value)
        store.audit("local-super-admin", "settings.updated", "settings", None, {"keys": list(payload.values)})
        log_governance(db, "INFO", "settings.updated", {"keys": list(payload.values)})
        await events.publish("settings.updated", {"keys": list(payload.values)})
        await events.publish("governance.updated", {"source": "settings"})
        return store.list_settings()

    @app.get("/api/engines/status")
    async def engine_status():
        statuses = await registry.status_all()
        now = utc_now()
        for item in statuses:
            db.execute(
                "INSERT INTO engine_checks(engine_id,available,version,detail,checked_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(engine_id) DO UPDATE SET available=excluded.available,version=excluded.version,detail=excluded.detail,checked_at=excluded.checked_at",
                (item["engine_id"], int(bool(item["available"])), item.get("version"), str(item.get("detail", "")), now),
            )
        await events.publish("engines.updated", {"checked_at": now})
        return {"items": statuses, "checked_at": now}

    @app.get("/api/model-profiles")
    async def model_profiles():
        profiles = registry.profiles()
        enriched = {}
        for profile_id, profile in profiles.items():
            missing = []
            for key in ("model", "diffusion_model", "high_noise_diffusion_model", "vae", "llm", "clip_l", "clip_g", "t5xxl", "clip_vision"):
                value = profile.get(key)
                if value and not Path(str(value)).expanduser().is_file():
                    missing.append({"field": key, "path": str(value)})
            enriched[profile_id] = {**profile, "ready": not missing, "missing_files": missing}
        return {"items": enriched}

    @app.get("/api/governance/snapshot")
    async def governance_snapshot():
        snapshot = read_governance_snapshot(db)
        response = JSONResponse(snapshot)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Type"] = "application/json"
        return response

    @app.patch("/api/governance/tasks/{task_id}")
    async def governance_task(task_id: str, payload: GovernanceTaskPatch):
        if not update_task(db, task_id, payload.status, payload.evidence):
            raise HTTPException(status_code=404, detail="Governance task not found")
        await events.publish("governance.updated", {"source": "task", "task_id": task_id})
        return read_governance_snapshot(db)

    @app.get("/api/events")
    async def event_stream():
        return StreamingResponse(events.stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/backups")
    async def make_backup(payload: BackupRequest):
        result = create_backup(db, config, include_assets=payload.include_assets, include_outputs=payload.include_outputs)
        log_governance(db, "INFO", "backup.created", result)
        await events.publish("governance.updated", {"source": "backup"})
        return result

    @app.get("/api/backups")
    async def list_backups():
        items = []
        for path in sorted(config.backups_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
            items.append({"path": str(path), "name": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
        return {"items": items}

    @app.post("/api/backups/restore")
    async def restore(payload: RestoreRequest):
        result = restore_backup(db, config, Path(payload.backup_path), replace_existing=payload.replace_existing)
        store.initialize_defaults()
        seed_governance(db)
        log_governance(db, "WARN", "backup.restored", {"path": payload.backup_path})
        await events.publish("governance.updated", {"source": "restore"})
        return result

    @app.post("/api/admin/shutdown", status_code=202)
    async def shutdown():
        if not config.allow_shutdown_endpoint:
            raise HTTPException(status_code=403, detail="Shutdown endpoint disabled")

        async def terminate() -> None:
            await asyncio.sleep(0.4)
            os.kill(os.getpid(), signal.SIGTERM)

        asyncio.create_task(terminate())
        return {"status": "shutting_down"}

    bundled_docs = Path(__file__).resolve().parent / "docs"
    source_docs = Path(__file__).resolve().parents[3] / "docs"
    docs_dir = bundled_docs if bundled_docs.is_dir() else source_docs
    if docs_dir.is_dir():
        app.mount("/docs-files", StaticFiles(directory=str(docs_dir), html=False), name="docs-files")
    if not config.frontend_dir.is_dir():
        raise RuntimeError(f"Frontend directory not found: {config.frontend_dir}")
    app.mount("/", StaticFiles(directory=str(config.frontend_dir), html=True), name="frontend")
    return app


app = create_app()
