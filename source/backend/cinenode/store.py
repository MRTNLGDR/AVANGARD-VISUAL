from __future__ import annotations

import json
import mimetypes
import shutil
import sys
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .config import AppConfig
from .database import Database
from .schemas import ProjectCreate, ProjectUpdate, WorkflowGraph
from .util import new_id, sha256_file, utc_now


def _default_engine_settings(config: AppConfig) -> dict[str, Any]:
    exe = ".exe" if sys.platform == "win32" else ""
    return {
        "sd_cpp": {
            "label": "stable-diffusion.cpp",
            "enabled": True,
            "binary_path": str(config.engines_dir / "stable-diffusion.cpp" / "bin" / f"sd-cli{exe}"),
            "ffmpeg_path": "ffmpeg",
            "timeout_seconds": 14400,
        },
        "wangp": {
            "label": "WanGP / Wan2GP — integração externa opcional",
            "enabled": False,
            "root_path": "",
            "python_path": "",
            "config_path": "",
            "cli_args": ["--attention", "sdpa", "--profile", "4"],
            "timeout_seconds": 14400,
        },
        "comfyui": {
            "label": "ComfyUI local",
            "enabled": True,
            "base_url": "http://127.0.0.1:8188",
            "timeout_seconds": 14400,
        },
        "realesrgan": {
            "label": "Real-ESRGAN NCNN Vulkan",
            "enabled": True,
            "binary_path": str(config.engines_dir / "realesrgan-ncnn-vulkan" / f"realesrgan-ncnn-vulkan{exe}"),
            "models_path": str(config.engines_dir / "realesrgan-ncnn-vulkan" / "models"),
            "timeout_seconds": 14400,
        },
        "rife": {
            "label": "RIFE NCNN Vulkan",
            "enabled": True,
            "binary_path": str(config.engines_dir / "rife-ncnn-vulkan" / f"rife-ncnn-vulkan{exe}"),
            "models_path": str(config.engines_dir / "rife-ncnn-vulkan" / "rife-v4.6"),
            "timeout_seconds": 14400,
        },
        "ffmpeg": {
            "label": "FFmpeg",
            "enabled": True,
            "binary_path": "ffmpeg",
            "probe_path": "ffprobe",
            "timeout_seconds": 14400,
        },
        "ollama": {
            "label": "Ollama local LLM/VLM",
            "enabled": True,
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen3:8b-q4_K_M",
            "vision_model": "qwen2.5vl:7b-q4_K_M",
            "timeout_seconds": 600,
        },
        "opencode": {
            "label": "OpenCode — agente de código e reparo de workflow",
            "enabled": True,
            "binary_path": "opencode",
            "model": "ollama/qwen3:8b-q4_K_M",
            "timeout_seconds": 900,
        },
        "trellis_cpp": {
            "label": "trellis.cpp — image-to-3D local",
            "enabled": True,
            "binary_path": str(config.engines_dir / "trellis.cpp" / f"trellis-cli{exe}"),
            "root_path": str(config.engines_dir / "trellis.cpp"),
            "models_path": str(config.models_dir / "trellis2"),
            "timeout_seconds": 14400,
        },
        "triposr": {
            "label": "TripoSR — image-to-3D local",
            "enabled": True,
            "root_path": str(config.engines_dir / "TripoSR"),
            "python_path": str(config.engines_dir / "TripoSR" / ("venv/Scripts/python.exe" if sys.platform == "win32" else "venv/bin/python")),
            "script_path": str(config.engines_dir / "TripoSR" / "run.py"),
            "timeout_seconds": 14400,
        },
        "generic_3d_cli": {
            "label": "CLI 3D local configurável",
            "enabled": False,
            "command": [],
            "timeout_seconds": 14400,
        },
        "blender": {
            "label": "Blender headless — conversão e preview 3D",
            "enabled": True,
            "binary_path": "blender",
            "timeout_seconds": 14400,
        },
    }


def _default_provider_settings() -> dict[str, Any]:
    return {
        "cloud.freepik": {
            "label": "Freepik API",
            "enabled": False,
            "api_key_env": "FREEPIK_API_KEY",
            "base_url": "https://api.freepik.com/v1/ai",
            "timeout_seconds": 3600,
            "poll_interval_seconds": 2,
        },
        "cloud.replicate": {
            "label": "Replicate",
            "enabled": False,
            "api_key_env": "REPLICATE_API_TOKEN",
            "base_url": "https://api.replicate.com/v1",
            "timeout_seconds": 3600,
            "poll_interval_seconds": 2,
        },
        "cloud.fal": {
            "label": "fal.ai",
            "enabled": False,
            "api_key_env": "FAL_KEY",
            "base_url": "https://queue.fal.run",
            "timeout_seconds": 3600,
            "poll_interval_seconds": 2,
            "store_io": True,
        },
        "cloud.tripo": {
            "label": "Tripo AI Platform API v2",
            "enabled": False,
            "api_key_env": "TRIPO_API_KEY",
            "base_url": "https://api.tripo3d.ai/v2/openapi",
            "timeout_seconds": 3600,
            "poll_interval_seconds": 3,
        },
        "cloud.generic_rest": {
            "label": "Provider REST compatível",
            "enabled": False,
            "api_key_env": "GENERIC_PROVIDER_API_KEY",
            "endpoint": "",
            "auth_type": "bearer",
            "timeout_seconds": 3600,
            "poll_interval_seconds": 2,
        },
    }


def _deep_defaults(current: Any, defaults: Any) -> Any:
    """Add new default keys without overwriting user configuration."""
    if not isinstance(defaults, dict):
        return current if current is not None else defaults
    result = dict(current) if isinstance(current, dict) else {}
    for key, value in defaults.items():
        if key not in result:
            result[key] = value
        elif isinstance(value, dict):
            result[key] = _deep_defaults(result[key], value)
    return result

def _default_model_profiles(config: AppConfig) -> dict[str, Any]:
    return {
        "z-image-turbo-fast": {
            "label": "Z-Image Turbo — rápido",
            "kind": "image",
            "engine": "sd_cpp",
            "ready": False,
            "diffusion_model": str(config.models_dir / "z-image-turbo" / "z_image_turbo-Q3_K.gguf"),
            "vae": str(config.models_dir / "z-image-turbo" / "ae.safetensors"),
            "llm": str(config.models_dir / "z-image-turbo" / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
            "defaults": {"width": 1024, "height": 1024, "steps": 8, "cfg_scale": 1.0, "sampling_method": "euler"},
        },
        "flux-fast-quantized": {
            "label": "FLUX quantizado — qualidade",
            "kind": "image",
            "engine": "sd_cpp",
            "ready": False,
            "diffusion_model": str(config.models_dir / "flux" / "flux1-schnell-Q4_K_M.gguf"),
            "vae": str(config.models_dir / "flux" / "ae.safetensors"),
            "clip_l": str(config.models_dir / "flux" / "clip_l.safetensors"),
            "t5xxl": str(config.models_dir / "flux" / "t5xxl-Q5_K_M.gguf"),
            "defaults": {"width": 1024, "height": 1024, "steps": 4, "cfg_scale": 1.0, "sampling_method": "euler"},
        },
        "wan21-t2v-1.3b-fast": {
            "label": "Wan 2.1 T2V 1.3B — rápido",
            "kind": "video",
            "engine": "sd_cpp",
            "ready": False,
            "diffusion_model": str(config.models_dir / "wan21" / "wan2.1_t2v_1.3B_fp16.safetensors"),
            "vae": str(config.models_dir / "wan21" / "wan_2.1_vae.safetensors"),
            "t5xxl": str(config.models_dir / "wan21" / "umt5-xxl-encoder-Q5_K_M.gguf"),
            "defaults": {"width": 832, "height": 480, "steps": 20, "cfg_scale": 6.0, "frames": 33, "fps": 16, "flow_shift": 3.0},
        },
        "wan22-t2v-a14b-quality": {
            "label": "Wan 2.2 T2V A14B — qualidade",
            "kind": "video",
            "engine": "sd_cpp",
            "ready": False,
            "diffusion_model": str(config.models_dir / "wan22" / "Wan2.2-T2V-A14B-LowNoise-Q5_K_M.gguf"),
            "high_noise_diffusion_model": str(config.models_dir / "wan22" / "Wan2.2-T2V-A14B-HighNoise-Q5_K_M.gguf"),
            "vae": str(config.models_dir / "wan22" / "wan_2.1_vae.safetensors"),
            "t5xxl": str(config.models_dir / "wan22" / "umt5-xxl-encoder-Q5_K_M.gguf"),
            "defaults": {"width": 832, "height": 480, "steps": 10, "high_noise_steps": 8, "cfg_scale": 3.5, "frames": 33, "fps": 16, "flow_shift": 3.0},
        },
        "wan21-i2v-14b-first-frame": {
            "label": "Wan 2.1 I2V 14B Q4 — primeiro frame",
            "kind": "video",
            "engine": "sd_cpp",
            "ready": False,
            "diffusion_model": str(config.models_dir / "wan21" / "wan2.1-i2v-14b-720p-Q4_K_M.gguf"),
            "vae": str(config.models_dir / "wan21" / "wan_2.1_vae.safetensors"),
            "t5xxl": str(config.models_dir / "wan21" / "umt5-xxl-encoder-Q5_K_M.gguf"),
            "clip_vision": str(config.models_dir / "wan21" / "clip_vision_h.safetensors"),
            "source": "city96/Wan2.1-I2V-14B-720P-gguf",
            "sha256": {"diffusion_model": "ffecd91e4b636d8e3e43f3fa388218158ba447109547bde777c6d67ef4fe42a4", "clip_vision": "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161"},
            "defaults": {"width": 1280, "height": 720, "steps": 20, "cfg_scale": 6.0, "frames": 81, "fps": 16, "flow_shift": 5.0},
        },
        "wan21-flf2v-14b-720p-q4": {
            "label": "Wan 2.1 FLF2V 14B Q4 — start + end frame",
            "kind": "video",
            "engine": "sd_cpp",
            "ready": False,
            "diffusion_model": str(config.models_dir / "wan21" / "wan2.1-flf2v-14b-720p-Q4_K_M.gguf"),
            "vae": str(config.models_dir / "wan21" / "wan_2.1_vae.safetensors"),
            "t5xxl": str(config.models_dir / "wan21" / "umt5-xxl-encoder-Q5_K_M.gguf"),
            "clip_vision": str(config.models_dir / "wan21" / "clip_vision_h.safetensors"),
            "source": "city96/Wan2.1-FLF2V-14B-720P-gguf",
            "sha256": {"diffusion_model": "7652d7d8b0795009ff21ed83d806af762aae8a8faa8640dd07b3a67e4dfab445", "clip_vision": "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161"},
            "defaults": {"width": 1280, "height": 720, "steps": 20, "cfg_scale": 6.0, "frames": 81, "fps": 16, "flow_shift": 5.0},
        },
        "trellis2-fast": {
            "label": "TRELLIS.2 / trellis.cpp — 3D local",
            "kind": "mesh",
            "engine": "trellis_cpp",
            "ready": False,
            "models_path": str(config.models_dir / "trellis2"),
            "defaults": {"resolution": 512, "faces": 500000, "atlas_size": 2048},
        },
    }


class Store:
    def __init__(self, db: Database, config: AppConfig):
        self.db = db
        self.config = config

    def initialize_defaults(self) -> None:
        defaults = {
            "app.profile": {"display_name": "Administrador local", "role": "super_admin"},
            "app.preferences": {"theme": "dark", "governance_poll_ms": 15000, "open_browser": True},
            "engines": _default_engine_settings(self.config),
            "providers": _default_provider_settings(),
            "model_profiles": _default_model_profiles(self.config),
            "runtime": {"max_parallel_gpu_jobs": 1, "max_parallel_cpu_jobs": 2, "auto_resume_interrupted_jobs": False},
        }
        for key, value in defaults.items():
            current = self.get_setting(key)
            merged = _deep_defaults(current, value)
            if current != merged:
                self.set_setting(key, merged)

    def get_setting(self, key: str) -> Any | None:
        row = self.db.query_one("SELECT value_json FROM settings WHERE key = ?", (key,))
        return self.db.load_json(row["value_json"]) if row else None

    def list_settings(self) -> dict[str, Any]:
        rows = self.db.query("SELECT key, value_json FROM settings ORDER BY key")
        return {row["key"]: self.db.load_json(row["value_json"]) for row in rows}

    def set_setting(self, key: str, value: Any) -> None:
        now = utc_now()
        self.db.execute(
            "INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, self.db.dump_json(value), now),
        )

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM projects ORDER BY updated_at DESC")
        return [self._project_row(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return self._project_row(row)

    def create_project(self, payload: ProjectCreate) -> dict[str, Any]:
        project_id = new_id("prj")
        now = utc_now()
        self.db.execute(
            "INSERT INTO projects(id,name,description,graph_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (project_id, payload.name, payload.description, self.db.dump_json(payload.graph.model_dump()), now, now),
        )
        self.audit("local-super-admin", "project.created", "project", project_id, {"name": payload.name})
        return self.get_project(project_id)

    def update_project(self, project_id: str, payload: ProjectUpdate) -> dict[str, Any]:
        current = self.get_project(project_id)
        name = payload.name if payload.name is not None else current["name"]
        description = payload.description if payload.description is not None else current["description"]
        graph = payload.graph.model_dump() if payload.graph is not None else current["graph"]
        now = utc_now()
        self.db.execute(
            "UPDATE projects SET name=?, description=?, graph_json=?, updated_at=? WHERE id=?",
            (name, description, self.db.dump_json(graph), now, project_id),
        )
        self.audit("local-super-admin", "project.updated", "project", project_id, {"name": name})
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> None:
        self.get_project(project_id)
        self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.audit("local-super-admin", "project.deleted", "project", project_id, {})

    def _project_row(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["graph"] = self.db.load_json(row.pop("graph_json"), {"version": 1, "nodes": [], "edges": [], "metadata": {}})
        return row

    def create_job(self, project_id: str | None, graph: WorkflowGraph) -> dict[str, Any]:
        job_id = new_id("job")
        now = utc_now()
        self.db.execute(
            "INSERT INTO jobs(id,project_id,status,progress,graph_json,created_at) VALUES(?,?,?,?,?,?)",
            (job_id, project_id, "QUEUED", 0.0, self.db.dump_json(graph.model_dump()), now),
        )
        self.audit("local-super-admin", "job.queued", "job", job_id, {"project_id": project_id})
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return self._job_row(row)

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),))
        return [self._job_row(row) for row in rows]

    def _job_row(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["graph"] = self.db.load_json(row.pop("graph_json"), {})
        row["result"] = self.db.load_json(row.pop("result_json"), None)
        row["cancel_requested"] = bool(row["cancel_requested"])
        return row

    def update_job(self, job_id: str, **changes: Any) -> None:
        allowed = {
            "status", "progress", "current_node_id", "result_json", "error_code",
            "error_message", "cancel_requested", "started_at", "finished_at"
        }
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Invalid job fields: {sorted(invalid)}")
        if not changes:
            return
        assignments = ",".join(f"{key}=?" for key in changes)
        values = [self.db.dump_json(value) if key == "result_json" and value is not None else value for key, value in changes.items()]
        self.db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*values, job_id))

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return job
        self.update_job(job_id, cancel_requested=1)
        return self.get_job(job_id)

    def retry_job(self, job_id: str) -> dict[str, Any]:
        old = self.get_job(job_id)
        graph = WorkflowGraph.model_validate(old["graph"])
        return self.create_job(old["project_id"], graph)

    def recover_interrupted_jobs(self) -> int:
        return self.db.execute(
            "UPDATE jobs SET status='FAILED', error_code='PROCESS_INTERRUPTED', "
            "error_message='The previous application process stopped while this job was running.', "
            "finished_at=? WHERE status='RUNNING'",
            (utc_now(),),
        )

    def add_asset(
        self,
        path: Path,
        kind: str,
        project_id: str | None = None,
        job_id: str | None = None,
        original_name: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = path.resolve()
        if not path.exists() or not path.is_file():
            raise ValueError(f"Asset does not exist: {path}")
        asset_id = new_id("ast")
        guessed = mimetypes.guess_type(path.name)[0]
        now = utc_now()
        metadata = dict(metadata or {})
        metadata.setdefault("sha256", sha256_file(path))
        self.db.execute(
            "INSERT INTO assets(id,project_id,job_id,kind,path,original_name,mime_type,size_bytes,metadata_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                asset_id, project_id, job_id, kind, str(path), original_name,
                mime_type or guessed or "application/octet-stream", path.stat().st_size,
                self.db.dump_json(metadata), now,
            ),
        )
        self.audit("system", "asset.created", "asset", asset_id, {"path": str(path), "kind": kind})
        return self.get_asset(asset_id)

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Asset not found")
        row["metadata"] = self.db.load_json(row.pop("metadata_json"), {})
        return row

    def list_assets(self, limit: int = 200, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            rows = self.db.query(
                "SELECT * FROM assets WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, max(1, min(limit, 1000))),
            )
        else:
            rows = self.db.query("SELECT * FROM assets ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),))
        result = []
        for row in rows:
            row["metadata"] = self.db.load_json(row.pop("metadata_json"), {})
            result.append(row)
        return result

    def audit(self, actor: str, action: str, target_type: str | None, target_id: str | None, detail: Any) -> None:
        self.db.execute(
            "INSERT INTO audit_events(created_at,actor,action,target_type,target_id,detail_json) VALUES(?,?,?,?,?,?)",
            (utc_now(), actor, action, target_type, target_id, self.db.dump_json(detail)),
        )

    def copy_upload(self, source: Path, safe_name: str) -> Path:
        destination = self.config.uploads_dir / f"{new_id('upload')}_{safe_name}"
        shutil.copy2(source, destination)
        return destination
