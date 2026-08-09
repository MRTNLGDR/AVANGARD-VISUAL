from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..providers import FalProvider, FreepikProvider, GenericRestProvider, ReplicateProvider, TripoCloudProvider
from ..store import Store
from .common import EngineExecutionError
from .comfyui import ComfyUIEngine
from .llm import LocalLLMEngine
from .mesh import LocalMeshEngines
from .postprocess import PostProcessEngines
from .sd_cpp import StableDiffusionCppEngine
from .wangp import WanGPEngine


PROVIDER_CATALOG: list[dict[str, Any]] = [
    {
        "id": "local.sd_cpp", "label": "stable-diffusion.cpp", "scope": "local",
        "capabilities": ["image", "image_edit", "video", "image_to_video", "first_last_frame"],
        "notes": "Leve/quantizado. Img2img usa -i/--strength; FLF2V usa -i + --end-img com checkpoint compatível.",
    },
    {
        "id": "local.comfyui", "label": "ComfyUI", "scope": "local",
        "capabilities": ["image", "image_edit", "video", "first_last_frame", "multi_reference", "audio", "mesh"],
        "notes": "Capacidades dependem do workflow API JSON e custom nodes instalados.",
    },
    {
        "id": "local.wangp", "label": "WanGP / Wan2GP", "scope": "local",
        "capabilities": ["image", "video", "first_last_frame", "multi_reference"],
        "notes": "Integração externa opcional; não é redistribuída como white-label.",
    },
    {
        "id": "local.ollama", "label": "Ollama", "scope": "local",
        "capabilities": ["llm", "vision", "agent"],
        "notes": "LLM/VLM local. OpenCode continua restrito a código e reparo de workflow.",
    },
    {
        "id": "local.trellis_cpp", "label": "trellis.cpp", "scope": "local",
        "capabilities": ["image_to_3d"],
        "notes": "Geração local de GLB a partir de referência única.",
    },
    {
        "id": "local.triposr", "label": "TripoSR", "scope": "local",
        "capabilities": ["image_to_3d"],
        "notes": "Cada imagem é uma reconstrução independente; não é tratado como fusão multiview. Normalmente produz OBJ; conversão GLB pode usar Blender.",
    },
    {
        "id": "local.generic_3d_cli", "label": "CLI 3D local configurável", "scope": "local",
        "capabilities": ["text_to_3d", "image_to_3d", "multiview_to_3d"],
        "notes": "Sem comando presumido: exige command[] explícito com {{prompt}}, {{input}}, {{references_json}} e {{output}}.",
    },
    {
        "id": "cloud.freepik", "label": "Freepik API", "scope": "cloud",
        "api_key_env": "FREEPIK_API_KEY",
        "capabilities": ["prompt", "vision", "image", "image_edit", "video", "first_last_frame", "multi_reference"],
        "models": ["seedream-v5-lite", "flux-2-pro", "kling-v2-1-std", "kling-o1-std-video-reference", "runway-4-5", "ltx-2-pro"],
    },
    {
        "id": "cloud.replicate", "label": "Replicate", "scope": "cloud",
        "api_key_env": "REPLICATE_API_TOKEN",
        "capabilities": ["image", "image_edit", "video", "first_last_frame", "multi_reference", "audio", "mesh"],
        "models": [], "notes": "O modelo owner/name ou version é explícito por nó.",
    },
    {
        "id": "cloud.fal", "label": "fal.ai", "scope": "cloud",
        "api_key_env": "FAL_KEY",
        "capabilities": ["image", "image_edit", "video", "first_last_frame", "multi_reference", "audio", "mesh"],
        "models": [], "notes": "O endpoint fal-ai/... é explícito por nó.",
    },
    {
        "id": "cloud.tripo", "label": "Tripo AI Platform API v2", "scope": "cloud",
        "api_key_env": "TRIPO_API_KEY",
        "capabilities": ["text_to_3d", "image_to_3d", "multiview_to_3d"],
        "models": ["v3.1-20260211"],
    },
    {
        "id": "cloud.generic_rest", "label": "REST compatível", "scope": "cloud",
        "api_key_env": "GENERIC_PROVIDER_API_KEY",
        "capabilities": ["image", "image_edit", "video", "audio", "mesh"],
        "models": [], "notes": "Contrato configurável para providers não nativos.",
    },
]


class EngineRegistry:
    def __init__(self, store: Store, config: AppConfig):
        self.store = store
        self.config = config

    def _settings(self) -> dict[str, Any]:
        return self.store.get_setting("engines") or {}

    def _provider_settings(self) -> dict[str, Any]:
        return self.store.get_setting("providers") or {}

    def profiles(self) -> dict[str, Any]:
        return self.store.get_setting("model_profiles") or {}

    def provider_catalog(self) -> list[dict[str, Any]]:
        settings = self._provider_settings()
        engines = self._settings()
        result: list[dict[str, Any]] = []
        for item in PROVIDER_CATALOG:
            value = dict(item)
            provider_id = str(value["id"])
            if provider_id.startswith("cloud."):
                cfg = settings.get(provider_id) or {}
                env_name = str(cfg.get("api_key_env") or value.get("api_key_env") or "")
                value.update({
                    "enabled": bool(cfg.get("enabled", False)),
                    "configured": bool(env_name and os.getenv(env_name, "").strip()),
                    "api_key_env": env_name,
                    "base_url": cfg.get("base_url") or cfg.get("endpoint") or "",
                })
            else:
                local_key = provider_id.removeprefix("local.")
                aliases = {"sd_cpp": "sd_cpp", "comfyui": "comfyui", "wangp": "wangp", "ollama": "ollama", "trellis_cpp": "trellis_cpp", "triposr": "triposr", "generic_3d_cli": "generic_3d_cli"}
                cfg = engines.get(aliases.get(local_key, local_key)) or {}
                value.update({"enabled": bool(cfg.get("enabled", True)), "configured": True})
            result.append(value)
        return result

    def _sd_cpp_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        merged = dict(settings.get("sd_cpp") or {})
        ffmpeg = settings.get("ffmpeg") or {}
        merged.setdefault("ffmpeg_path", ffmpeg.get("binary_path", "ffmpeg"))
        return merged

    def _profile(self, profile_id: str, expected_kind: str | None = None) -> dict[str, Any]:
        profile = self.profiles().get(profile_id)
        if not profile:
            raise EngineExecutionError("MODEL_PROFILE_MISSING", f"Perfil de modelo não encontrado: {profile_id}")
        if expected_kind and profile.get("kind") != expected_kind:
            raise EngineExecutionError("MODEL_KIND_MISMATCH", f"O perfil {profile_id} não é do tipo {expected_kind}")
        return profile

    def _mesh(self) -> LocalMeshEngines:
        settings = self._settings()
        return LocalMeshEngines(
            settings.get("trellis_cpp") or {}, settings.get("triposr") or {},
            settings.get("generic_3d_cli") or {}, settings.get("blender") or {},
        )

    async def status_all(self) -> list[dict[str, Any]]:
        settings = self._settings()
        statuses: list[dict[str, Any]] = []
        statuses.append(await StableDiffusionCppEngine(self._sd_cpp_settings(settings)).status())
        statuses.extend(await LocalLLMEngine(settings.get("ollama") or {}, settings.get("opencode") or {}).status())
        statuses.extend(await PostProcessEngines(settings.get("realesrgan") or {}, settings.get("rife") or {}, settings.get("ffmpeg") or {}).status())
        statuses.append(await ComfyUIEngine(settings.get("comfyui") or {}).status())
        statuses.append(await WanGPEngine(settings.get("wangp") or {}).status())
        statuses.extend(await self._mesh().status())
        return statuses

    async def provider_status_all(self) -> list[dict[str, Any]]:
        engine_statuses = {item["engine_id"]: item for item in await self.status_all()}
        result: list[dict[str, Any]] = []
        local_map = {
            "local.sd_cpp": "sd_cpp", "local.comfyui": "comfyui", "local.wangp": "wangp",
            "local.ollama": "ollama", "local.trellis_cpp": "trellis_cpp",
            "local.triposr": "triposr", "local.generic_3d_cli": "generic_3d_cli",
        }
        for item in self.provider_catalog():
            provider_id = item["id"]
            if provider_id in local_map:
                status = engine_statuses.get(local_map[provider_id], {"available": False, "detail": "status ausente"})
                result.append({**item, "available": bool(status.get("available")), "detail": status.get("detail"), "version": status.get("version")})
            else:
                configured = bool(item.get("configured"))
                result.append({**item, "available": configured and bool(item.get("enabled")), "detail": "chave presente; chamada ainda não executada" if configured else f"defina {item.get('api_key_env')}"})
        return result

    def _cloud_provider(self, provider_id: str):
        settings = self._provider_settings().get(provider_id) or {}
        if not bool(settings.get("enabled", False)):
            raise EngineExecutionError("PROVIDER_DISABLED", f"Provider desativado: {provider_id}")
        mapping = {
            "cloud.freepik": FreepikProvider,
            "cloud.replicate": ReplicateProvider,
            "cloud.fal": FalProvider,
            "cloud.tripo": TripoCloudProvider,
            "cloud.generic_rest": GenericRestProvider,
        }
        factory = mapping.get(provider_id)
        if not factory:
            raise EngineExecutionError("PROVIDER_NOT_SUPPORTED", f"Provider desconhecido: {provider_id}")
        return factory(settings)

    def normalize_provider(self, provider: str, default: str) -> str:
        return self._normalize_provider({"provider": provider}, default)

    @staticmethod
    def _normalize_provider(config: dict[str, Any], default: str) -> str:
        provider = str(config.get("provider") or config.get("engine") or default).strip()
        aliases = {
            "sd_cpp": "local.sd_cpp", "comfyui": "local.comfyui", "wangp": "local.wangp",
            "ollama": "local.ollama", "trellis_cpp": "local.trellis_cpp", "triposr": "local.triposr",
            "generic_3d_cli": "local.generic_3d_cli", "freepik": "cloud.freepik", "replicate": "cloud.replicate",
            "fal": "cloud.fal", "tripo": "cloud.tripo", "generic_rest": "cloud.generic_rest",
        }
        return aliases.get(provider, provider)


    async def plan_intent(
        self,
        brief: str,
        target: str,
        reference_roles: list[str],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Ask the local LLM for a bounded production intent, never arbitrary code.

        The returned object may influence shot count and direction, but the executable
        DAG is still built and validated by trusted application code.
        """
        settings = self._settings()
        engine = LocalLLMEngine(settings.get("ollama") or {}, settings.get("opencode") or {})
        schema = {
            "shot_count": "integer 1..8",
            "direction": "concise production direction",
            "continuity_rules": ["rule"],
            "camera_plan": ["shot description"],
        }
        raw = await engine.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Você é um planejador audiovisual. Responda APENAS JSON válido. "
                        "Não altere o target. Não invente providers, caminhos, código ou assets. "
                        "Planeje entre 1 e 8 planos e regras de continuidade."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"target": target, "brief": brief, "reference_roles": reference_roles, "response_schema": schema},
                        ensure_ascii=False,
                    ),
                },
            ],
            model=model or None,
            json_mode=True,
            temperature=0.2,
        )
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise EngineExecutionError("AGENT_PLAN_INVALID_JSON", "O planejador local retornou JSON inválido", raw[:3000]) from exc
        if not isinstance(data, dict):
            raise EngineExecutionError("AGENT_PLAN_INVALID", "O planejador local não retornou um objeto JSON")
        try:
            shot_count = max(1, min(8, int(data.get("shot_count", 1))))
        except (TypeError, ValueError):
            shot_count = 1
        direction = str(data.get("direction") or "").strip()[:4000]
        continuity = [str(item).strip()[:500] for item in (data.get("continuity_rules") or []) if str(item).strip()][:20]
        camera_plan = [str(item).strip()[:800] for item in (data.get("camera_plan") or []) if str(item).strip()][:8]
        return {
            "shot_count": shot_count,
            "direction": direction,
            "continuity_rules": continuity,
            "camera_plan": camera_plan,
            "model": model or (settings.get("ollama") or {}).get("model"),
        }

    async def enhance_prompt(self, prompt: str, config: dict[str, Any], **runtime: Any) -> str:
        provider = self._normalize_provider(config, "local.ollama")
        if provider == "cloud.freepik":
            result = await self._cloud_provider(provider).invoke("enhance_prompt", prompt, "", [], None, config, cancel_check=runtime.get("cancel_check"))
            text = str(result.get("text") or "").strip()
            if not text:
                raise EngineExecutionError("LLM_EMPTY_RESPONSE", "Freepik Improve Prompt não retornou texto", str(result)[:2000])
            return text
        if provider not in {"local.ollama", "opencode", "local.opencode"}:
            raise EngineExecutionError("PROVIDER_OPERATION_UNSUPPORTED", f"Provider não suporta aprimoramento de prompt: {provider}")
        settings = self._settings()
        engine = LocalLLMEngine(settings.get("ollama") or {}, settings.get("opencode") or {})
        local_provider = "opencode" if provider in {"opencode", "local.opencode"} or config.get("provider") == "opencode" else "ollama"
        return await engine.enhance(prompt, provider=local_provider, model=config.get("model"), instruction=config.get("instruction"), **runtime)

    async def vision(self, prompt: str, references: list[dict[str, Any]], config: dict[str, Any], **runtime: Any) -> str:
        provider = self._normalize_provider(config, "local.ollama")
        if provider == "local.ollama":
            settings = self._settings()
            engine = LocalLLMEngine(settings.get("ollama") or {}, settings.get("opencode") or {})
            return await engine.vision([Path(str(item["path"])) for item in references], prompt, model=config.get("model"))
        if provider == "cloud.freepik":
            result = await self._cloud_provider(provider).invoke("vision", prompt, "", references, None, config, cancel_check=runtime.get("cancel_check"))
            text = str(result.get("text") or "").strip()
            if not text:
                raise EngineExecutionError("VISION_EMPTY_RESPONSE", "Freepik Image-to-Prompt não retornou descrição", str(result)[:2000])
            return text
        raise EngineExecutionError("PROVIDER_OPERATION_UNSUPPORTED", f"Provider não suporta visão: {provider}")

    async def invoke_cloud(
        self,
        provider_id: str,
        operation: str,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path,
        config: dict[str, Any],
        **runtime: Any,
    ) -> dict[str, Any]:
        provider = self._cloud_provider(provider_id)
        if provider_id == "cloud.tripo":
            if operation != "mesh":
                raise EngineExecutionError("PROVIDER_OPERATION_UNSUPPORTED", "Tripo cloud é usado somente para operações 3D")
            return await provider.invoke_mesh(prompt, negative, references, output_path, config, cancel_check=runtime.get("cancel_check"))
        return await provider.invoke(operation, prompt, negative, references, output_path, config, cancel_check=runtime.get("cancel_check"))

    async def _comfy(
        self,
        output_path: Path,
        config: dict[str, Any],
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        *,
        preferred_suffixes: set[str] | None = None,
        **runtime: Any,
    ) -> dict[str, Any]:
        workflow_path = Path(str(config.get("workflow_path", ""))).expanduser().resolve()
        if not workflow_path.is_file():
            raise EngineExecutionError("COMFYUI_WORKFLOW_MISSING", "Workflow ComfyUI API JSON não encontrado", str(workflow_path))
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EngineExecutionError("COMFYUI_WORKFLOW_INVALID", "Workflow ComfyUI contém JSON inválido", str(exc)) from exc
        comfy = ComfyUIEngine(self._settings().get("comfyui") or {})
        uploaded_references = await comfy.upload_inputs(references) if references else []
        roles = {str(item.get("role") or "reference"): str(item.get("path")) for item in uploaded_references}
        paths = [str(item.get("path")) for item in uploaded_references]
        tokens: dict[str, Any] = {
            "{{prompt}}": prompt,
            "{{negative_prompt}}": negative,
            "{{seed}}": int(config.get("seed", -1)),
            "{{width}}": int(config.get("width", 1024)),
            "{{height}}": int(config.get("height", 1024)),
            "{{frames}}": int(config.get("frames", 33)),
            "{{fps}}": int(config.get("fps", 16)),
            "{{input_image}}": paths[0] if paths else "",
            "{{start_image}}": roles.get("start_frame", paths[0] if paths else ""),
            "{{end_image}}": roles.get("end_frame", ""),
            "{{mask_image}}": roles.get("mask", ""),
            "{{reference_images_json}}": json.dumps(paths),
        }
        files = await comfy.execute_workflow(
            workflow, output_path.parent, tokens,
            cancel_check=runtime.get("cancel_check"),
        )
        existing = [path.resolve() for path in files if path.is_file() and path.stat().st_size > 0]
        if not existing:
            raise EngineExecutionError("COMFYUI_OUTPUT_MISSING", "ComfyUI concluiu sem arquivo verificável")
        preferred = {item.lower() for item in (preferred_suffixes or set())}
        selected = next((path for path in existing if path.suffix.lower() in preferred), None) if preferred else existing[0]
        if preferred and selected is None:
            raise EngineExecutionError(
                "COMFYUI_OUTPUT_KIND_MISMATCH",
                "O workflow ComfyUI terminou, mas não gerou o tipo de arquivo esperado.",
                f"esperado={sorted(preferred)}; recebido={[path.suffix.lower() for path in existing]}",
            )
        assert selected is not None
        return {"path": str(selected), "paths": [str(path) for path in existing], "engine": "local.comfyui"}

    async def generate_image(
        self,
        prompt: str,
        negative: str,
        output_path: Path,
        config: dict[str, Any],
        *,
        references: list[dict[str, Any]] | None = None,
        operation: str = "image",
        **runtime: Any,
    ) -> dict[str, Any]:
        references = list(references or [])
        provider = self._normalize_provider(config, "local.sd_cpp")
        settings = self._settings()
        if provider == "local.sd_cpp":
            mask = next((Path(str(item["path"])) for item in references if item.get("role") == "mask"), None)
            visual = [Path(str(item["path"])) for item in references if item.get("role") != "mask"]
            if len(visual) > 1:
                raise EngineExecutionError(
                    "ENGINE_CAPABILITY_MISSING",
                    "stable-diffusion.cpp aceita uma imagem de entrada por execução; use ComfyUI/cloud para multirreferência.",
                )
            input_image = visual[0] if visual else None
            if operation == "image_edit" and input_image is None:
                raise EngineExecutionError("REFERENCE_INPUT_MISSING", "image.edit local precisa de uma imagem de entrada")
            profile = self._profile(str(config.get("profile_id", "z-image-turbo-fast")), "image")
            return await StableDiffusionCppEngine(self._sd_cpp_settings(settings)).generate_image(
                profile, prompt, negative, output_path, config,
                input_image=input_image, mask_image=mask, **runtime,
            )
        if provider == "local.comfyui":
            return await self._comfy(
                output_path, config, prompt, negative, references,
                preferred_suffixes={".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".exr"},
                **runtime,
            )
        if provider == "local.wangp":
            payload = dict(config.get("wangp_settings") or {})
            payload.setdefault("prompt", prompt)
            payload.setdefault("negative_prompt", negative)
            if references:
                payload.setdefault("image_start", str(references[0]["path"]))
                payload.setdefault("reference_images", [str(item["path"]) for item in references])
            files = await WanGPEngine(settings.get("wangp") or {}).generate(payload, output_path.parent, output_path.parent / ".wangp-work", **runtime)
            return {"path": str(files[0]), "paths": [str(path) for path in files], "engine": "local.wangp"}
        if provider.startswith("cloud."):
            return await self.invoke_cloud(provider, "image_edit" if operation == "image_edit" else "image", prompt, negative, references, output_path, config, **runtime)
        raise EngineExecutionError("ENGINE_NOT_SUPPORTED", f"Provider de imagem não suportado: {provider}")

    async def generate_video(
        self,
        prompt: str,
        negative: str,
        output_path: Path,
        config: dict[str, Any],
        *,
        references: list[dict[str, Any]] | None = None,
        input_image: Path | None = None,
        **runtime: Any,
    ) -> dict[str, Any]:
        references = list(references or [])
        if input_image and not references:
            references = [{"path": str(input_image), "role": "start_frame", "weight": 1.0}]
        provider = self._normalize_provider(config, "local.sd_cpp")
        settings = self._settings()
        start = next((Path(str(item["path"])) for item in references if item.get("role") == "start_frame"), None)
        end = next((Path(str(item["path"])) for item in references if item.get("role") == "end_frame"), None)
        general = [Path(str(item["path"])) for item in references if item.get("role") not in {"start_frame", "end_frame", "mask"}]
        if provider == "local.sd_cpp":
            if end and start is None:
                raise EngineExecutionError("START_FRAME_MISSING", "FLF2V local exige start_frame e end_frame")
            if len(general) > (0 if start else 1):
                raise EngineExecutionError(
                    "ENGINE_CAPABILITY_MISSING",
                    "stable-diffusion.cpp não funde referências gerais; use ComfyUI/WanGP/cloud para multirreferência.",
                )
            default_profile = (
                "wan21-flf2v-14b-720p-q4" if end else
                "wan21-i2v-14b-first-frame" if (start or general) else
                "wan21-t2v-1.3b-fast"
            )
            profile = self._profile(str(config.get("profile_id") or default_profile), "video")
            return await StableDiffusionCppEngine(self._sd_cpp_settings(settings)).generate_video(
                profile, prompt, negative, output_path, config,
                input_image=start or (general[0] if general else None), end_image=end, **runtime,
            )
        if provider == "local.wangp":
            payload = dict(config.get("wangp_settings") or {})
            payload.setdefault("prompt", prompt)
            payload.setdefault("negative_prompt", negative)
            if start:
                payload.setdefault("image_start", str(start))
            elif general:
                payload.setdefault("image_start", str(general[0]))
            if end:
                payload.setdefault("image_end", str(end))
            if references:
                payload.setdefault("reference_images", [str(item["path"]) for item in references])
            files = await WanGPEngine(settings.get("wangp") or {}).generate(payload, output_path.parent, output_path.parent / ".wangp-work", **runtime)
            return {"path": str(files[0]), "paths": [str(path) for path in files], "engine": "local.wangp"}
        if provider == "local.comfyui":
            return await self._comfy(
                output_path, config, prompt, negative, references,
                preferred_suffixes={".mp4", ".mov", ".mkv", ".webm", ".avi", ".gif"},
                **runtime,
            )
        if provider.startswith("cloud."):
            return await self.invoke_cloud(provider, "video", prompt, negative, references, output_path, config, **runtime)
        raise EngineExecutionError("ENGINE_NOT_SUPPORTED", f"Provider de vídeo não suportado: {provider}")

    async def generate_mesh(
        self,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path,
        config: dict[str, Any],
        **runtime: Any,
    ) -> dict[str, Any]:
        provider = self._normalize_provider(config, "local.trellis_cpp")
        if provider == "local.comfyui":
            return await self._comfy(
                output_path, config, prompt, negative, references,
                preferred_suffixes={".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usdz"},
                **runtime,
            )
        if provider == "cloud.tripo":
            return await self.invoke_cloud(provider, "mesh", prompt, negative, references, output_path, config, **runtime)
        if provider in {"cloud.replicate", "cloud.fal", "cloud.generic_rest"}:
            return await self.invoke_cloud(provider, "mesh", prompt, negative, references, output_path, config, **runtime)
        if provider.startswith("local."):
            return await self._mesh().generate(provider, prompt, references, output_path, config, **runtime)
        raise EngineExecutionError("ENGINE_NOT_SUPPORTED", f"Provider 3D não suportado: {provider}")

    def mesh(self) -> LocalMeshEngines:
        return self._mesh()

    def postprocess(self) -> PostProcessEngines:
        settings = self._settings()
        return PostProcessEngines(settings.get("realesrgan") or {}, settings.get("rife") or {}, settings.get("ffmpeg") or {})
