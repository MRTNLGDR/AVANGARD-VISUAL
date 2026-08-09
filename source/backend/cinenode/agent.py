from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import AgentPlanRequest, ProjectCreate, WorkflowEdge, WorkflowGraph, WorkflowNode
from .engines import EngineExecutionError, EngineRegistry
from .store import Store
from .workflow import validate_workflow


@dataclass(slots=True)
class _GraphBuilder:
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    x: float = 0

    def node(self, node_id: str, node_type: str, config: dict[str, Any], *, x: float | None = None, y: float = 0) -> str:
        xpos = self.x if x is None else x
        self.nodes.append(WorkflowNode(id=node_id, type=node_type, position={"x": xpos, "y": y}, config=config))
        self.x = max(self.x, xpos + 270)
        return node_id

    def edge(self, source: str, target: str, source_handle: str, target_handle: str, suffix: str = "") -> None:
        edge_id = f"e-{source}-{target}-{source_handle}-{target_handle}{suffix}"
        self.edges.append(WorkflowEdge(id=edge_id[:150], source=source, target=target, source_handle=source_handle, target_handle=target_handle))


class WorkflowAgent:
    """Builds an executable graph from a brief and typed references.

    Planning can use a bounded local Ollama JSON call. The resulting graph is always
    rebuilt and validated by trusted code; auto mode records the exact LLM failure
    before falling back to deterministic rules. Creative inference remains explicit
    in graph nodes and never becomes a hidden success path.
    """

    def __init__(self, store: Store, registry: EngineRegistry):
        self.store = store
        self.registry = registry

    def _select_provider(self, request: AgentPlanRequest) -> tuple[str, list[str]]:
        notes: list[str] = []
        if request.provider and request.provider != "auto":
            return request.provider, notes
        roles = {item.role for item in request.references}
        if not request.local_first:
            provider = "cloud.tripo" if request.target == "3d" else "cloud.freepik"
            notes.append("Modo cloud-first selecionado: o provider automático usa Freepik para imagem/vídeo e Tripo para 3D.")
            return provider, notes
        if request.target == "image":
            base_roles = {"reference", "character", "product", "composition", "environment"}
            has_single_base = len(request.references) == 1 and next(iter(roles), "") in base_roles
            provider = "local.sd_cpp" if has_single_base else "local.comfyui" if request.references else "local.sd_cpp"
            if request.references and not has_single_base:
                notes.append("Edição/multirreferência local usa ComfyUI porque stable-diffusion.cpp aceita somente uma imagem de entrada e não implementa referência de estilo/máscara genérica por si só.")
        elif request.target in {"video", "film"}:
            if "start_frame" in roles and "end_frame" in roles:
                provider = "local.sd_cpp"
                notes.append("Start/end local usa Wan 2.1 FLF2V com -i + --end-img; exige o checkpoint FLF2V e clip vision.")
            elif len(request.references) > 1:
                provider = "local.comfyui"
            else:
                provider = "local.sd_cpp"
        else:
            if len(request.references) > 1:
                provider = "local.comfyui"
                notes.append("O plano multiview local usa um workflow ComfyUI 3D explícito; sem workflow/pesos instalados ele falha de forma acionável em vez de usar somente a primeira vista.")
            elif request.references:
                provider = "local.trellis_cpp"
            else:
                provider = "cloud.tripo"
                notes.append("Não há text-to-3D local leve validado no pacote; texto puro usa Tripo cloud ou uma CLI 3D explicitamente configurada.")
        return provider, notes


    @staticmethod
    def _required_capability(request: AgentPlanRequest) -> str:
        roles = {item.role for item in request.references}
        if request.target == "image":
            if request.references:
                return "image_edit" if roles.intersection({"reference", "character", "product", "composition", "environment", "mask"}) else "multi_reference"
            return "image"
        if request.target in {"video", "film"}:
            if {"start_frame", "end_frame"}.issubset(roles):
                return "first_last_frame"
            if len(request.references) > 1:
                return "multi_reference"
            return "image_to_video" if request.references else "video"
        if len(request.references) > 1:
            return "multiview_to_3d"
        if request.references:
            return "image_to_3d"
        return "text_to_3d"

    @staticmethod
    def _provider_candidates(request: AgentPlanRequest, preferred: str) -> list[str]:
        capability = WorkflowAgent._required_capability(request)
        local: list[str]
        cloud: list[str]
        if request.target == "image":
            if capability == "image":
                local = ["local.sd_cpp", "local.comfyui", "local.wangp"]
            else:
                local = ["local.sd_cpp", "local.comfyui", "local.wangp"]
            cloud = ["cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"]
        elif request.target in {"video", "film"}:
            local = ["local.sd_cpp", "local.comfyui", "local.wangp"]
            cloud = ["cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"]
        else:
            if capability == "image_to_3d":
                local = ["local.trellis_cpp", "local.triposr", "local.comfyui", "local.generic_3d_cli"]
            elif capability == "multiview_to_3d":
                local = ["local.comfyui", "local.generic_3d_cli"]
            else:
                local = ["local.generic_3d_cli", "local.comfyui"]
            cloud = ["cloud.tripo", "cloud.replicate", "cloud.fal", "cloud.generic_rest"]
        ordered = (local + cloud) if request.local_first else (cloud + local)
        result: list[str] = []
        for item in [preferred, *ordered]:
            if item not in result:
                result.append(item)
        return result

    @staticmethod
    def _dimensions(aspect_ratio: str, base: int = 1024) -> tuple[int, int]:
        ratios = {
            "1:1": (base, base), "4:3": (base, int(base * 3 / 4)), "3:2": (base, int(base * 2 / 3)),
            "16:9": (base, int(base * 9 / 16)), "9:16": (int(base * 9 / 16), base), "21:9": (base, int(base * 9 / 21)),
        }
        return ratios.get(aspect_ratio, ratios["16:9"])

    @staticmethod
    def _delivery(resolution: str) -> tuple[int, int] | None:
        return {"1080p": (1920, 1080), "4k": (3840, 2160), "8k": (7680, 4320)}.get(resolution)

    async def plan(self, request: AgentPlanRequest) -> dict[str, Any]:
        preferred_provider, provider_notes = self._select_provider(request)
        statuses = {item["id"]: item for item in await self.registry.provider_status_all()}
        provider = preferred_provider
        fallback_used = False
        if request.provider == "auto" and not bool((statuses.get(provider) or {}).get("available")):
            alternate = next(
                (candidate for candidate in self._provider_candidates(request, preferred_provider)
                 if bool((statuses.get(candidate) or {}).get("available"))),
                None,
            )
            if alternate and alternate != provider:
                provider_notes.append(
                    f"{provider} não está pronto neste computador; o agente selecionou {alternate}, que passou no diagnóstico local/configuração."
                )
                provider = alternate
                fallback_used = True
            else:
                detail = str((statuses.get(provider) or {}).get("detail") or "provider/engine não instalado ou não configurado")
                provider_notes.append(
                    f"{provider} foi mantido como destino preferido, porém o pré-voo está bloqueado: {detail}. O job não será tratado como sucesso até essa dependência existir."
                )
        llm_plan: dict[str, Any] | None = None
        planner_error: dict[str, str] | None = None
        if request.use_llm and request.planner_mode in {"auto", "llm"}:
            try:
                llm_plan = await self.registry.plan_intent(
                    request.brief, request.target, [item.role for item in request.references],
                    model=request.agent_model or None,
                )
            except EngineExecutionError as exc:
                if request.planner_mode == "llm":
                    raise
                planner_error = {"code": exc.code, "message": exc.message, "detail": exc.detail or ""}
        width, height = self._dimensions(request.aspect_ratio)
        builder = _GraphBuilder([], [])
        explanations = [
            "O brief vira um grafo executável, não uma demonstração visual.",
            "As referências mantêm papéis explícitos do upload até o provider.",
            *provider_notes,
        ]
        if llm_plan:
            explanations.append("Ollama retornou um plano JSON limitado; o DAG final foi construído e validado por código confiável.")
        elif planner_error:
            explanations.append(f"Planejador LLM indisponível ({planner_error['code']}); modo auto continuou com regras determinísticas, sem fingir inferência.")
        else:
            explanations.append("Planejamento estrutural por regras; a direção criativa por LLM ocorre apenas se o nó Diretor IA estiver habilitado.")

        prompt_id = builder.node("brief", "input.text", {"text": request.brief}, x=20, y=40)
        refs_id: str | None = None
        vision_id: str | None = None
        start_selection = next((item for item in request.references if item.role == "start_frame"), None)
        end_selection = next((item for item in request.references if item.role == "end_frame"), None)
        image_base_roles = {"reference", "character", "product", "composition", "environment"}
        image_base_selection = next((item for item in request.references if item.role in image_base_roles), None) if request.target == "image" else None
        mask_selection = next((item for item in request.references if item.role == "mask"), None) if request.target == "image" else None
        if request.target == "image" and mask_selection and not image_base_selection:
            raise EngineExecutionError("IMAGE_BASE_REFERENCE_MISSING", "Uma máscara exige uma imagem-base conectada.")
        # Resolve all assets during planning. Missing records/files fail before a project is created.
        for selection in request.references:
            asset = self.store.get_asset(selection.asset_id)
            from pathlib import Path as _Path
            if not _Path(str(asset["path"])).is_file():
                raise EngineExecutionError("REFERENCE_FILE_MISSING", "Arquivo de referência não existe", str(asset["path"]))
        start_asset_id: str | None = None
        end_asset_id: str | None = None
        image_base_asset_id: str | None = None
        mask_asset_id: str | None = None
        if request.references:
            refs_id = builder.node(
                "references", "input.references",
                {"references": [item.model_dump() for item in request.references]}, x=20, y=260,
            )
            if request.use_llm:
                vision_id = builder.node(
                    "vision", "vision.analyze",
                    {
                        "provider": "local.ollama", "model": "",
                        "prompt": "Analise identidade, personagem, objeto, materiais, estilo, composição, ambiente, câmera e continuidade que devem ser preservados.",
                    },
                    x=300, y=260,
                )
                builder.edge(refs_id, vision_id, "references", "references")
        if start_selection:
            start_asset_id = builder.node("start-frame", "input.asset", {"asset_id": start_selection.asset_id}, x=300, y=520)
        if end_selection:
            end_asset_id = builder.node("end-frame", "input.asset", {"asset_id": end_selection.asset_id}, x=300, y=650)
        if image_base_selection:
            image_base_asset_id = builder.node("base-image", "input.asset", {"asset_id": image_base_selection.asset_id}, x=300, y=520)
        if mask_selection:
            mask_asset_id = builder.node("mask-image", "input.asset", {"asset_id": mask_selection.asset_id}, x=300, y=650)

        if request.use_llm:
            director_id = builder.node(
                "director", "agent.director",
                {
                    "provider": "local.ollama", "model": "", "prompt": "",
                    "instruction": (
                        "Atue como diretor cinematográfico e supervisor de continuidade. Transforme o brief e a análise das referências "
                        "em um prompt executável. Preserve identidade, geometria, materiais, posição relativa e intenção. "
                        "Inclua lente, câmera, movimento, luz, ação e restrições; não invente elementos conflitantes."
                        + (("\nPLANO ESTRUTURAL DO AGENTE: " + str(llm_plan.get("direction"))) if llm_plan and llm_plan.get("direction") else "")
                        + (("\nREGRAS DE CONTINUIDADE: " + "; ".join(llm_plan.get("continuity_rules") or [])) if llm_plan else "")
                    ),
                },
                x=590, y=80,
            )
            builder.edge(prompt_id, director_id, "text", "brief")
            if vision_id:
                builder.edge(vision_id, director_id, "analysis", "context")
            direction_handle = "direction"
        else:
            director_id = prompt_id
            direction_handle = "text"
            explanations.append("Direção por LLM desativada: o brief é enviado diretamente ao gerador, sem chamada oculta.")

        decisions: dict[str, Any] = {
            "target": request.target,
            "provider": provider,
            "preferred_provider": preferred_provider,
            "provider_ready": bool((statuses.get(provider) or {}).get("available")),
            "provider_status": statuses.get(provider),
            "fallback_used": fallback_used,
            "required_capability": self._required_capability(request),
            "model": request.model,
            "local_first": request.local_first,
            "aspect_ratio": request.aspect_ratio,
            "duration_seconds": request.duration_seconds,
            "output_resolution": request.output_resolution,
            "planner": "ollama-json+validated-builder" if llm_plan else "offline-rules+runtime-director" if request.use_llm else "offline-rules-direct",
            "planner_error": planner_error,
            "llm_plan": llm_plan,
            "reference_roles": [item.role for item in request.references],
        }

        if request.target == "image":
            image_node_type = "image.edit" if image_base_selection else "image.generate"
            generate = builder.node(
                "image", image_node_type,
                {
                    "provider": provider, "model": request.model, "profile_id": "z-image-turbo-fast",
                    "prompt": "", "negative_prompt": "", "aspect_ratio": request.aspect_ratio,
                    "width": width, "height": height, "steps": 8, "seed": -1,
                    "workflow_path": "", "payload": {},
                }, x=880, y=80,
            )
            builder.edge(director_id, generate, direction_handle, "prompt")
            if image_base_asset_id:
                builder.edge(image_base_asset_id, generate, "media", "image")
            if mask_asset_id:
                builder.edge(mask_asset_id, generate, "media", "mask")
            supplementary = [
                item for item in request.references
                if item is not image_base_selection and item is not mask_selection
            ]
            if supplementary:
                generation_refs = builder.node(
                    "image-references", "input.references",
                    {"references": [item.model_dump() for item in supplementary]}, x=300, y=780,
                )
                builder.edge(generation_refs, generate, "references", "references")
            tail = generate
            delivery = self._delivery(request.output_resolution)
            if delivery:
                upscale = builder.node("image-upscale", "image.upscale", {"scale": 4, "model": "realesrgan-x4plus", "tile": 0}, x=1160, y=80)
                builder.edge(tail, upscale, "image", "image")
                resize = builder.node("image-delivery", "image.resize", {"width": delivery[0], "height": delivery[1]}, x=1430, y=80)
                builder.edge(upscale, resize, "image", "image")
                tail = resize
            preview = builder.node("preview", "output.preview", {}, x=1710, y=80)
            builder.edge(tail, preview, "image", "result")

        elif request.target in {"video", "film"}:
            roles = {item.role for item in request.references}
            if "start_frame" in roles and "end_frame" in roles:
                generator_type = "video.first_last"
            elif len(request.references) > 1:
                generator_type = "video.reference"
            else:
                generator_type = "video.generate"
            if generator_type == "video.generate" and provider == "local.comfyui" and not request.references:
                provider = "local.sd_cpp"
                decisions["provider"] = provider

            # A start/end-frame request is one continuous generated take. Splitting it
            # into three shots would reuse the same boundary frames and break continuity.
            requested_shots = int((llm_plan or {}).get("shot_count", 3 if request.target == "film" else 1))
            shot_count = 1 if generator_type == "video.first_last" else max(1, min(8, requested_shots if request.target == "film" else 1))
            shot_nodes: list[str] = []
            shot_duration = max(1, request.duration_seconds // shot_count)
            for index in range(shot_count):
                prompt_source = director_id
                if shot_count > 1:
                    compose = builder.node(
                        f"shot-prompt-{index + 1}", "prompt.compose",
                        {
                            "prefix": "", "separator": "\n\n",
                            "suffix": f"\nPLANO {index + 1}/{shot_count}: mantenha continuidade absoluta; produza uma ação e enquadramento distintos e complementares.",
                        },
                        x=880, y=40 + index * 250,
                    )
                    builder.edge(director_id, compose, direction_handle, "parts", f"-{index}")
                    prompt_source = compose
                generator = builder.node(
                    f"video-{index + 1}", generator_type,
                    {
                        "provider": provider, "model": request.model,
                        "profile_id": (
                            "wan21-flf2v-14b-720p-q4" if generator_type == "video.first_last" and provider == "local.sd_cpp" else
                            "wan21-i2v-14b-first-frame" if request.references and provider == "local.sd_cpp" else
                            "wan21-t2v-1.3b-fast"
                        ), "prompt": "", "negative_prompt": "",
                        "duration": shot_duration, "aspect_ratio": request.aspect_ratio,
                        "width": 832, "height": 480, "frames": max(17, shot_duration * 16 + 1),
                        "fps": 16, "steps": 20, "seed": -1,
                        "workflow_path": "", "wangp_settings": {}, "payload": {},
                    },
                    x=1160 if shot_count > 1 else 880, y=40 + index * 250,
                )
                source_handle = "text" if shot_count > 1 else direction_handle
                builder.edge(prompt_source, generator, source_handle, "prompt", f"-{index}")
                if generator_type == "video.first_last":
                    if not start_asset_id or not end_asset_id:
                        raise ValueError("Start/end frame planning requires both typed assets")
                    builder.edge(start_asset_id, generator, "media", "start_frame", f"-start-{index}")
                    builder.edge(end_asset_id, generator, "media", "end_frame", f"-end-{index}")
                    if refs_id:
                        builder.edge(refs_id, generator, "references", "references", f"-extras-{index}")
                    explanations.append("Start frame e end frame são conectados em portas dedicadas e validados antes da execução.")
                elif refs_id:
                    builder.edge(refs_id, generator, "references", "references", f"-{index}")
                shot_nodes.append(generator)

            if len(shot_nodes) > 1:
                concat = builder.node("film-edit", "video.concat", {"transition_seconds": 0.0}, x=1450, y=250)
                for index, shot in enumerate(shot_nodes):
                    builder.edge(shot, concat, "video", "videos", f"-{index}")
                tail = concat
            else:
                tail = shot_nodes[0]

            delivery = self._delivery(request.output_resolution)
            if delivery:
                upscale = builder.node("video-upscale", "video.upscale", {"scale": 4 if request.output_resolution == "8k" else 2, "model": "realesrgan-x4plus", "target_fps": 24}, x=1730, y=250)
                builder.edge(tail, upscale, "video", "video")
                resize = builder.node("video-delivery", "video.resize", {"width": delivery[0], "height": delivery[1], "codec": "h265", "crf": 16}, x=2000, y=250)
                builder.edge(upscale, resize, "video", "video")
                tail = resize
            export = builder.node("film-export", "media.export", {"codec": "h265", "crf": 16, "fps": 24, "filename": "filme-final.mp4"}, x=2270, y=250)
            builder.edge(tail, export, "video", "media")
            preview = builder.node("preview", "output.preview", {}, x=2540, y=250)
            builder.edge(export, preview, "media", "result")

        else:  # 3d
            mesh = builder.node(
                "mesh", "mesh.generate",
                {
                    "provider": provider, "model": request.model, "prompt": "", "negative_prompt": "",
                    "texture": True, "pbr": True, "texture_quality": "detailed",
                    "resolution": 512, "faces": 500000, "atlas_size": 2048, "payload": {},
                }, x=880, y=80,
            )
            builder.edge(director_id, mesh, direction_handle, "prompt")
            if refs_id:
                builder.edge(refs_id, mesh, "references", "references")
            export = builder.node("mesh-export", "mesh.export", {"format": "glb", "filename": "modelo-final.glb"}, x=1160, y=50)
            builder.edge(mesh, export, "mesh", "mesh")
            mesh_preview = builder.node("mesh-turntable", "mesh.preview", {"width": 1024, "height": 1024, "frames": 120, "fps": 30}, x=1160, y=270)
            builder.edge(mesh, mesh_preview, "mesh", "mesh")
            final = builder.node("preview", "output.preview", {}, x=1430, y=50)
            builder.edge(export, final, "mesh", "result")
            explanations.append("O GLB e o turntable são saídas separadas; Blender é necessário apenas para conversão/preview.")

        graph = WorkflowGraph(version=2, nodes=builder.nodes, edges=builder.edges, metadata={
            "created_by": "cinenode-agent", "brief": request.brief, "target": request.target,
            "provider": provider, "reference_count": len(request.references),
        })
        validation = validate_workflow(graph, for_execution=False)
        project = None
        if request.create_project:
            name = (request.project_name or f"Agente · {request.target.title()}").strip()
            project = self.store.create_project(ProjectCreate(name=name, description=request.brief[:4000], graph=graph))
        return {"graph": graph, "explanation": explanations, "decisions": decisions, "validation": validation, "project": project}
