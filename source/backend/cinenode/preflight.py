from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .engines.registry import EngineRegistry
from .schemas import WorkflowGraph, WorkflowNode
from .store import Store
from .workflow import validate_workflow


_PROVIDER_DEFAULTS = {
    "agent.director": "local.ollama",
    "llm.enhance": "local.ollama",
    "vision.analyze": "local.ollama",
    "image.generate": "local.sd_cpp",
    "image.edit": "local.sd_cpp",
    "video.generate": "local.sd_cpp",
    "video.first_last": "local.sd_cpp",
    "video.reference": "local.comfyui",
    "mesh.generate": "local.trellis_cpp",
}

_POSTPROCESS_ENGINES = {
    "image.upscale": "realesrgan",
    "image.resize": "ffmpeg",
    "video.extract_frame": "ffmpeg",
    "video.concat": "ffmpeg",
    "video.resize": "ffmpeg",
    "video.interpolate": "rife",
    "video.upscale": "realesrgan",
    "media.export": "ffmpeg",
    "mesh.preview": "blender",
}


def _check(node: WorkflowNode | None, code: str, ready: bool, message: str, detail: Any = None, *, severity: str = "ERROR") -> dict[str, Any]:
    return {
        "node_id": node.id if node else None,
        "node_type": node.type if node else None,
        "code": code,
        "ready": bool(ready),
        "severity": "INFO" if ready else severity,
        "message": message,
        "detail": detail,
    }


def _profile_missing(profile: dict[str, Any]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for key in ("model", "diffusion_model", "high_noise_diffusion_model", "vae", "llm", "clip_l", "clip_g", "t5xxl", "clip_vision"):
        value = profile.get(key)
        if value and not Path(str(value)).expanduser().is_file():
            missing.append({"field": key, "path": str(value)})
    return missing


async def preflight_workflow(store: Store, registry: EngineRegistry, graph: WorkflowGraph) -> dict[str, Any]:
    validation = validate_workflow(graph, for_execution=True)
    checks: list[dict[str, Any]] = []
    if not validation["valid"]:
        for error in validation["errors"]:
            checks.append(_check(None, str(error.get("code") or "WORKFLOW_INVALID"), False, str(error.get("message") or "Workflow inválido"), error))

    provider_statuses = {item["id"]: item for item in await registry.provider_status_all()}
    engine_statuses = {item["engine_id"]: item for item in await registry.status_all()}
    profiles = registry.profiles()

    for node in graph.nodes:
        if node.type == "input.asset":
            asset_id = str(node.config.get("asset_id") or "").strip()
            if not asset_id:
                checks.append(_check(node, "ASSET_ID_MISSING", False, "Asset não selecionado."))
                continue
            try:
                asset = store.get_asset(asset_id)
                path = Path(str(asset["path"])).resolve()
                checks.append(_check(node, "ASSET_READY", path.is_file(), "Asset disponível." if path.is_file() else "Arquivo do asset não existe.", str(path)))
            except HTTPException:
                checks.append(_check(node, "ASSET_NOT_FOUND", False, "Asset não existe no banco.", asset_id))
            continue

        if node.type == "input.references":
            selections = node.config.get("references") or []
            if not isinstance(selections, list) or not selections:
                checks.append(_check(node, "REFERENCES_MISSING", False, "Nenhuma referência selecionada."))
                continue
            for item in selections:
                asset_id = str(item.get("asset_id") or "") if isinstance(item, dict) else ""
                try:
                    asset = store.get_asset(asset_id)
                    path = Path(str(asset["path"])).resolve()
                    if not path.is_file():
                        checks.append(_check(node, "REFERENCE_FILE_MISSING", False, "Arquivo de referência não existe.", {"asset_id": asset_id, "path": str(path)}))
                except HTTPException:
                    checks.append(_check(node, "REFERENCE_NOT_FOUND", False, "Referência não existe no banco.", asset_id))
            if not any(item["node_id"] == node.id and not item["ready"] for item in checks):
                checks.append(_check(node, "REFERENCES_READY", True, f"{len(selections)} referência(s) disponível(is)."))
            continue

        default_provider = _PROVIDER_DEFAULTS.get(node.type)
        if default_provider:
            raw_provider = str(node.config.get("provider") or node.config.get("engine") or default_provider)
            provider = registry.normalize_provider(raw_provider, default_provider)
            status = provider_statuses.get(provider)
            ready = bool(status and status.get("available"))
            checks.append(_check(node, "PROVIDER_READY" if ready else "PROVIDER_NOT_READY", ready, f"Provider pronto: {provider}" if ready else f"Provider indisponível: {provider}", status or {"provider": provider}))

            if provider == "local.sd_cpp":
                profile_id = str(node.config.get("profile_id") or ("z-image-turbo-fast" if node.type.startswith("image.") else "wan21-t2v-1.3b-fast"))
                profile = profiles.get(profile_id)
                if not profile:
                    checks.append(_check(node, "MODEL_PROFILE_MISSING", False, "Perfil local não existe.", profile_id))
                else:
                    missing = _profile_missing(profile)
                    checks.append(_check(node, "MODEL_PROFILE_READY" if not missing else "MODEL_FILES_MISSING", not missing, f"Perfil pronto: {profile_id}" if not missing else f"Arquivos ausentes no perfil {profile_id}.", missing))
            elif provider == "local.comfyui":
                workflow_path = Path(str(node.config.get("workflow_path") or "")).expanduser()
                workflow_ready = workflow_path.is_file()
                checks.append(_check(node, "COMFY_WORKFLOW_READY" if workflow_ready else "COMFY_WORKFLOW_MISSING", workflow_ready, "Workflow ComfyUI API JSON disponível." if workflow_ready else "Selecione um workflow ComfyUI API JSON compatível.", str(workflow_path) if str(workflow_path) else ""))
            elif provider in {"cloud.replicate", "cloud.fal"}:
                model = str(node.config.get("model") or "").strip()
                checks.append(_check(node, "PROVIDER_MODEL_READY" if model else "PROVIDER_MODEL_MISSING", bool(model), "Modelo/endpoint configurado." if model else "Informe o modelo/endpoint deste provider."))
            elif provider == "cloud.generic_rest":
                endpoint = str(node.config.get("endpoint") or "").strip()
                checks.append(_check(node, "PROVIDER_ENDPOINT_READY" if endpoint else "PROVIDER_ENDPOINT_MISSING", bool(endpoint), "Endpoint REST configurado." if endpoint else "Informe um endpoint REST explícito."))
            continue

        engine_id = _POSTPROCESS_ENGINES.get(node.type)
        if engine_id:
            # media.export only requires FFmpeg for video. Treat absent FFmpeg as a
            # blocking preflight because the graph input kind is not known statically.
            status = engine_statuses.get(engine_id)
            ready = bool(status and status.get("available"))
            checks.append(_check(node, "ENGINE_READY" if ready else "ENGINE_NOT_READY", ready, f"Engine pronta: {engine_id}" if ready else f"Engine indisponível: {engine_id}", status or {"engine_id": engine_id}))

    blocking = [item for item in checks if not item["ready"] and item["severity"] == "ERROR"]
    return {
        "ready": validation["valid"] and not blocking,
        "validation": validation,
        "checks": checks,
        "blocking": blocking,
        "summary": {
            "total": len(checks),
            "ready": sum(1 for item in checks if item["ready"]),
            "blocked": len(blocking),
        },
    }
