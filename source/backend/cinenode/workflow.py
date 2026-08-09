from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import AppConfig
from .engines import EngineExecutionError, EngineRegistry
from .schemas import WorkflowEdge, WorkflowGraph, WorkflowNode
from .security import sanitize_filename
from .store import Store


REFERENCE_ROLES = [
    "reference", "character", "style", "composition", "product", "environment",
    "start_frame", "end_frame", "mask", "front", "left", "right", "back", "top", "bottom",
]
MEDIA_TYPES = {"image", "video", "audio", "mesh", "file", "media"}
IMAGE_PROVIDERS = ["local.sd_cpp", "local.comfyui", "local.wangp", "cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"]
VIDEO_PROVIDERS = ["local.sd_cpp", "local.comfyui", "local.wangp", "cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"]
MESH_PROVIDERS = ["local.comfyui", "local.trellis_cpp", "local.triposr", "local.generic_3d_cli", "cloud.tripo", "cloud.replicate", "cloud.fal", "cloud.generic_rest"]


def _port(
    port_id: str,
    data_type: str,
    label: str,
    *,
    required: bool = False,
    multiple: bool = False,
    accepts: list[str] | None = None,
    config_key: str | None = None,
) -> dict[str, Any]:
    return {
        "id": port_id,
        "type": data_type,
        "label": label,
        "required": required,
        "multiple": multiple,
        "accepts": accepts or [data_type],
        "config_key": config_key,
    }


def _field(key: str, label: str, field_type: str, default: Any = "", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": field_type, "default": default, **extra}


def _provider_fields(options: list[str], default: str) -> list[dict[str, Any]]:
    return [
        _field("provider", "Provider / engine", "select", default, options=options),
        _field("model", "Modelo/endpoint opcional", "text", ""),
        _field("endpoint", "Endpoint override opcional", "text", ""),
    ]


NODE_CATALOG: list[dict[str, Any]] = [
    {
        "type": "input.text", "category": "Entrada", "label": "Prompt / roteiro",
        "description": "Texto, roteiro, restrições ou instruções do agente.",
        "inputs": [], "outputs": [_port("text", "text", "Texto")],
        "fields": [_field("text", "Texto", "textarea", "", required=True)],
    },
    {
        "type": "input.asset", "category": "Entrada", "label": "Asset único",
        "description": "Imagem, vídeo, áudio, arquivo ou modelo 3D importado.",
        "inputs": [], "outputs": [_port("media", "media", "Mídia")],
        "fields": [_field("asset_id", "Asset", "asset", "", required=True)],
    },
    {
        "type": "input.references", "category": "Entrada", "label": "Referências múltiplas",
        "description": "Conjunto tipado: personagem, estilo, composição, start/end frame ou vistas 3D.",
        "inputs": [], "outputs": [_port("references", "references", "Referências")],
        "fields": [_field("references", "Referências e funções", "references", [], roles=REFERENCE_ROLES, required=True)],
    },
    {
        "type": "agent.director", "category": "Agente", "label": "Diretor IA",
        "description": "LLM local transforma brief e análise visual em direção cinematográfica executável.",
        "inputs": [
            _port("brief", "text", "Brief", required=True, config_key="prompt"),
            _port("context", "text", "Contexto", multiple=True),
        ],
        "outputs": [_port("direction", "text", "Direção")],
        "fields": [
            _field("provider", "Agente", "select", "local.ollama", options=["local.ollama", "opencode", "cloud.freepik"]),
            _field("model", "Modelo", "text", ""),
            _field("prompt", "Brief alternativo", "textarea", ""),
            _field("instruction", "Papel do diretor", "textarea", "Crie uma direção cinematográfica precisa, com continuidade visual, câmera, iluminação, ação, identidade e restrições. Retorne somente o prompt executável."),
        ],
    },
    {
        "type": "llm.enhance", "category": "Agente", "label": "Aprimorar prompt",
        "description": "Ollama/OpenCode local ou Freepik Improve Prompt.",
        "inputs": [_port("prompt", "text", "Prompt", required=True, config_key="prompt")],
        "outputs": [_port("text", "text", "Prompt final")],
        "fields": [
            _field("provider", "Provider", "select", "local.ollama", options=["local.ollama", "opencode", "cloud.freepik"]),
            _field("model", "Modelo opcional", "text", ""),
            _field("prompt", "Prompt alternativo", "textarea", ""),
            _field("instruction", "Instrução", "textarea", ""),
        ],
    },
    {
        "type": "vision.analyze", "category": "Agente", "label": "Analisar referências",
        "description": "VLM local ou Image-to-Prompt cloud descreve identidade, estilo e continuidade.",
        "inputs": [
            _port("references", "references", "Referências", required=True, multiple=True, accepts=["references", "image", "media"]),
            _port("question", "text", "Pergunta", config_key="prompt"),
        ],
        "outputs": [_port("analysis", "text", "Análise")],
        "fields": [
            _field("provider", "Provider", "select", "local.ollama", options=["local.ollama", "cloud.freepik"]),
            _field("model", "VLM", "text", ""),
            _field("prompt", "O que analisar", "textarea", "Identifique assunto, identidade, materiais, câmera, iluminação, estilo e tudo que deve permanecer consistente."),
        ],
    },
    {
        "type": "prompt.compose", "category": "Agente", "label": "Compor prompts",
        "description": "Concatena blocos de texto de forma determinística.",
        "inputs": [_port("parts", "text", "Partes", required=True, multiple=True)],
        "outputs": [_port("text", "text", "Prompt composto")],
        "fields": [
            _field("prefix", "Prefixo", "textarea", ""),
            _field("separator", "Separador", "text", "\n\n"),
            _field("suffix", "Sufixo", "textarea", ""),
        ],
    },
    {
        "type": "image.generate", "category": "Imagem", "label": "Gerar imagem",
        "description": "Text-to-image local ou cloud, com referências quando o provider suporta.",
        "inputs": [
            _port("prompt", "text", "Prompt", required=True, config_key="prompt"),
            _port("references", "references", "Referências", multiple=True, accepts=["references", "image", "media"]),
        ],
        "outputs": [_port("image", "image", "Imagem")],
        "fields": _provider_fields(IMAGE_PROVIDERS, "local.sd_cpp") + [
            _field("profile_id", "Perfil local", "model_profile", "z-image-turbo-fast", kind="image"),
            _field("prompt", "Prompt alternativo", "textarea", ""),
            _field("negative_prompt", "Prompt negativo", "textarea", ""),
            _field("aspect_ratio", "Proporção", "select", "16:9", options=["1:1", "4:3", "3:2", "16:9", "9:16", "21:9"]),
            _field("width", "Largura base", "number", 1024, min=256, max=8192, step=16),
            _field("height", "Altura base", "number", 576, min=256, max=8192, step=16),
            _field("steps", "Steps", "number", 8, min=1, max=150),
            _field("seed", "Seed", "number", -1),
            _field("workflow_path", "Workflow ComfyUI API JSON", "path", ""),
            _field("payload", "Payload avançado", "json", {}),
        ],
    },
    {
        "type": "image.edit", "category": "Imagem", "label": "Editar / transformar imagem",
        "description": "Edição generativa, variação, inpaint/outpaint ou transferência por provider real.",
        "inputs": [
            _port("prompt", "text", "Instrução", required=True, config_key="prompt"),
            _port("image", "image", "Imagem", required=True, accepts=["image", "media"]),
            _port("mask", "image", "Máscara", accepts=["image", "media"]),
            _port("references", "references", "Referências", multiple=True, accepts=["references", "image", "media"]),
        ],
        "outputs": [_port("image", "image", "Imagem editada")],
        "fields": _provider_fields(["local.sd_cpp", "local.comfyui", "local.wangp", "cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"], "local.sd_cpp") + [
            _field("prompt", "Instrução alternativa", "textarea", ""),
            _field("negative_prompt", "Prompt negativo", "textarea", ""),
            _field("width", "Largura", "number", 1024, min=256, max=8192, step=16),
            _field("height", "Altura", "number", 1024, min=256, max=8192, step=16),
            _field("seed", "Seed", "number", -1),
            _field("workflow_path", "Workflow ComfyUI API JSON", "path", ""),
            _field("payload", "Payload avançado", "json", {}),
        ],
    },
    {
        "type": "image.upscale", "category": "Pós", "label": "Upscale AI imagem",
        "description": "Real-ESRGAN NCNN Vulkan em tiles.",
        "inputs": [_port("image", "image", "Imagem", required=True, accepts=["image", "media"])],
        "outputs": [_port("image", "image", "Imagem ampliada")],
        "fields": [
            _field("scale", "Escala", "select", 4, options=[2, 3, 4]),
            _field("model", "Modelo", "select", "realesrgan-x4plus", options=["realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3"]),
            _field("tile", "Tile (0 auto)", "number", 0, min=0, max=2048),
        ],
    },
    {
        "type": "image.resize", "category": "Pós", "label": "Resize imagem",
        "description": "Resize Lanczos real por FFmpeg para dimensões 4K/8K ou customizadas.",
        "inputs": [_port("image", "image", "Imagem", required=True, accepts=["image", "media"])],
        "outputs": [_port("image", "image", "Imagem redimensionada")],
        "fields": [
            _field("width", "Largura", "number", 3840, min=64, max=16384),
            _field("height", "Altura", "number", 2160, min=64, max=16384),
        ],
    },
    {
        "type": "video.generate", "category": "Vídeo", "label": "Gerar take",
        "description": "Text-to-video ou image-to-video. Aceita uma referência/frame quando suportado.",
        "inputs": [
            _port("prompt", "text", "Prompt", required=True, config_key="prompt"),
            _port("references", "references", "Referências", multiple=True, accepts=["references", "image", "media"]),
        ],
        "outputs": [_port("video", "video", "Vídeo")],
        "fields": _provider_fields(VIDEO_PROVIDERS, "local.sd_cpp") + [
            _field("profile_id", "Perfil local", "model_profile", "wan21-t2v-1.3b-fast", kind="video"),
            _field("prompt", "Prompt alternativo", "textarea", ""),
            _field("negative_prompt", "Prompt negativo", "textarea", ""),
            _field("aspect_ratio", "Proporção", "select", "16:9", options=["1:1", "4:3", "16:9", "9:16", "21:9"]),
            _field("duration", "Duração (s)", "number", 5, min=1, max=60),
            _field("width", "Largura base", "number", 832, min=256, max=4096, step=16),
            _field("height", "Altura base", "number", 480, min=256, max=4096, step=16),
            _field("frames", "Frames", "number", 81, min=9, max=1001),
            _field("fps", "FPS", "number", 16, min=1, max=120),
            _field("steps", "Steps", "number", 20, min=1, max=100),
            _field("seed", "Seed", "number", -1),
            _field("workflow_path", "Workflow ComfyUI API JSON", "path", ""),
            _field("wangp_settings", "Settings WanGP", "json", {}),
            _field("payload", "Payload avançado", "json", {}),
        ],
    },
    {
        "type": "video.first_last", "category": "Vídeo", "label": "Vídeo start + end frame",
        "description": "Gera movimento entre quadro inicial e final; nunca ignora silenciosamente o end frame.",
        "inputs": [
            _port("prompt", "text", "Prompt", required=True, config_key="prompt"),
            _port("start_frame", "image", "Start frame", required=True, accepts=["image", "media"]),
            _port("end_frame", "image", "End frame", required=True, accepts=["image", "media"]),
            _port("references", "references", "Referências extras", multiple=True, accepts=["references", "image", "media"]),
        ],
        "outputs": [_port("video", "video", "Vídeo")],
        "fields": _provider_fields(["local.sd_cpp", "local.comfyui", "local.wangp", "cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"], "local.sd_cpp") + [
            _field("prompt", "Prompt alternativo", "textarea", ""),
            _field("negative_prompt", "Prompt negativo", "textarea", ""),
            _field("duration", "Duração", "number", 5, min=1, max=60),
            _field("aspect_ratio", "Proporção", "select", "16:9", options=["1:1", "4:3", "16:9", "9:16", "21:9"]),
            _field("workflow_path", "Workflow ComfyUI API JSON", "path", ""),
            _field("wangp_settings", "Settings WanGP", "json", {}),
            _field("payload", "Payload avançado", "json", {}),
        ],
    },
    {
        "type": "video.reference", "category": "Vídeo", "label": "Vídeo multirreferência",
        "description": "Personagem, produto, estilo, composição e ambiente enviados com papéis preservados.",
        "inputs": [
            _port("prompt", "text", "Prompt", required=True, config_key="prompt"),
            _port("references", "references", "Referências", required=True, multiple=True, accepts=["references", "image", "media"]),
        ],
        "outputs": [_port("video", "video", "Vídeo")],
        "fields": _provider_fields(["local.sd_cpp", "local.comfyui", "local.wangp", "cloud.freepik", "cloud.replicate", "cloud.fal", "cloud.generic_rest"], "local.sd_cpp") + [
            _field("prompt", "Prompt alternativo", "textarea", ""),
            _field("negative_prompt", "Prompt negativo", "textarea", ""),
            _field("duration", "Duração", "number", 5, min=1, max=60),
            _field("aspect_ratio", "Proporção", "select", "16:9", options=["1:1", "4:3", "16:9", "9:16", "21:9"]),
            _field("workflow_path", "Workflow ComfyUI API JSON", "path", ""),
            _field("wangp_settings", "Settings WanGP", "json", {}),
            _field("payload", "Payload avançado", "json", {}),
        ],
    },
    {
        "type": "video.extract_frame", "category": "Vídeo", "label": "Extrair frame",
        "description": "Extrai um quadro real de vídeo por timestamp com FFmpeg.",
        "inputs": [_port("video", "video", "Vídeo", required=True, accepts=["video", "media"])],
        "outputs": [_port("image", "image", "Frame")],
        "fields": [_field("at_seconds", "Tempo (s)", "number", 0.0, min=0, max=86400, step=0.01)],
    },
    {
        "type": "video.concat", "category": "Vídeo", "label": "Montar takes",
        "description": "Concatena dois ou mais vídeos reais com FFmpeg.",
        "inputs": [_port("videos", "video", "Vídeos", required=True, multiple=True, accepts=["video", "media"])],
        "outputs": [_port("video", "video", "Filme")],
        "fields": [_field("transition_seconds", "Montagem", "select", 0.0, options=[0.0])],
    },
    {
        "type": "video.resize", "category": "Pós", "label": "Resize vídeo 4K/8K",
        "description": "Resize Lanczos real por FFmpeg para entrega exata; não é upscale neural.",
        "inputs": [_port("video", "video", "Vídeo", required=True, accepts=["video", "media"])],
        "outputs": [_port("video", "video", "Vídeo redimensionado")],
        "fields": [
            _field("width", "Largura", "number", 3840, min=256, max=16384),
            _field("height", "Altura", "number", 2160, min=256, max=16384),
            _field("codec", "Codec", "select", "h265", options=["h264", "h265"]),
            _field("crf", "CRF", "number", 16, min=0, max=51),
        ],
    },
    {
        "type": "video.interpolate", "category": "Pós", "label": "Interpolar FPS",
        "description": "RIFE NCNN Vulkan ou minterpolate FFmpeg.",
        "inputs": [_port("video", "video", "Vídeo", required=True, accepts=["video", "media"])],
        "outputs": [_port("video", "video", "Vídeo interpolado")],
        "fields": [
            _field("engine", "Engine", "select", "rife", options=["rife", "ffmpeg"]),
            _field("target_fps", "FPS final", "number", 60, min=2, max=240),
        ],
    },
    {
        "type": "video.upscale", "category": "Pós", "label": "Upscale AI vídeo",
        "description": "Extrai frames, aplica Real-ESRGAN e recompõe preservando áudio.",
        "inputs": [_port("video", "video", "Vídeo", required=True, accepts=["video", "media"])],
        "outputs": [_port("video", "video", "Vídeo ampliado")],
        "fields": [
            _field("scale", "Escala", "select", 2, options=[2, 3, 4]),
            _field("model", "Modelo", "text", "realesrgan-x4plus"),
            _field("target_fps", "FPS", "number", 24, min=1, max=240),
        ],
    },
    {
        "type": "mesh.generate", "category": "3D", "label": "Gerar 3D",
        "description": "Text/image/multiview-to-3D local ou Tripo/Replicate/fal cloud.",
        "inputs": [
            _port("prompt", "text", "Prompt", config_key="prompt"),
            _port("references", "references", "Referências/vistas", multiple=True, accepts=["references", "image", "media"]),
        ],
        "outputs": [_port("mesh", "mesh", "Modelo 3D")],
        "fields": _provider_fields(MESH_PROVIDERS, "local.trellis_cpp") + [
            _field("prompt", "Prompt alternativo", "textarea", ""),
            _field("negative_prompt", "Prompt negativo", "textarea", ""),
            _field("texture", "Gerar textura", "checkbox", True),
            _field("pbr", "PBR", "checkbox", True),
            _field("texture_quality", "Qualidade textura", "select", "detailed", options=["standard", "detailed"]),
            _field("resolution", "Resolução local", "number", 512, min=128, max=2048),
            _field("faces", "Limite de faces", "number", 500000, min=1000, max=5000000),
            _field("atlas_size", "Atlas", "number", 2048, min=256, max=8192),
            _field("workflow_path", "Workflow ComfyUI 3D API JSON", "path", ""),
            _field("payload", "Payload avançado", "json", {}),
        ],
    },
    {
        "type": "mesh.preview", "category": "3D", "label": "Turntable 3D",
        "description": "Renderiza vídeo turntable real via Blender headless.",
        "inputs": [_port("mesh", "mesh", "Modelo 3D", required=True, accepts=["mesh", "media"])],
        "outputs": [_port("video", "video", "Preview")],
        "fields": [
            _field("width", "Largura", "number", 1024, min=256, max=4096),
            _field("height", "Altura", "number", 1024, min=256, max=4096),
            _field("frames", "Frames", "number", 120, min=12, max=1200),
            _field("fps", "FPS", "number", 30, min=1, max=120),
        ],
    },
    {
        "type": "mesh.export", "category": "3D", "label": "Exportar 3D",
        "description": "Converte ou copia modelo para GLB/GLTF usando Blender quando necessário.",
        "inputs": [_port("mesh", "mesh", "Modelo 3D", required=True, accepts=["mesh", "media"])],
        "outputs": [_port("mesh", "mesh", "Modelo exportado")],
        "fields": [
            _field("format", "Formato", "select", "glb", options=["glb", "gltf"]),
            _field("filename", "Nome", "text", "modelo-final.glb"),
        ],
    },
    {
        "type": "media.export", "category": "Saída", "label": "Exportar mídia",
        "description": "Encode final de vídeo ou cópia controlada de imagem/áudio/3D.",
        "inputs": [_port("media", "media", "Mídia", required=True, accepts=["media", "image", "video", "audio", "mesh", "file"])],
        "outputs": [_port("media", "media", "Arquivo final")],
        "fields": [
            _field("codec", "Codec de vídeo", "select", "h265", options=["h264", "h265", "prores", "av1"]),
            _field("crf", "CRF", "number", 16, min=0, max=51),
            _field("fps", "FPS opcional", "number", 0, min=0, max=240),
            _field("filename", "Nome", "text", "resultado-final.mp4"),
        ],
    },
    {
        "type": "output.preview", "category": "Saída", "label": "Saída / preview",
        "description": "Marca uma saída terminal sem alterar seus bytes.",
        "inputs": [_port("result", "any", "Resultado", required=True, accepts=["any"])],
        "outputs": [_port("result", "any", "Resultado")], "fields": [],
    },
]

CATALOG_BY_TYPE = {item["type"]: item for item in NODE_CATALOG}
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class WorkflowValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("Workflow inválido")
        self.errors = errors


def _ports(node_type: str, direction: str) -> list[dict[str, Any]]:
    item = CATALOG_BY_TYPE.get(node_type) or {}
    return list(item.get(direction) or [])


def _compatible(source_type: str, target: dict[str, Any]) -> bool:
    accepted = set(target.get("accepts") or [target.get("type")])
    if "any" in accepted or target.get("type") == "any":
        return True
    if source_type == "media" and accepted.intersection(MEDIA_TYPES):
        return True
    if source_type in MEDIA_TYPES and "media" in accepted:
        return True
    return source_type in accepted


def _resolve_binding(edge: WorkflowEdge, source: WorkflowNode, target: WorkflowNode) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    outputs = _ports(source.type, "outputs")
    inputs = _ports(target.type, "inputs")
    source_port = next((port for port in outputs if port["id"] == edge.source_handle), None) if edge.source_handle else None
    target_port = next((port for port in inputs if port["id"] == edge.target_handle), None) if edge.target_handle else None
    if source_port and not target_port:
        target_port = next((port for port in inputs if _compatible(str(source_port["type"]), port)), None)
    elif target_port and not source_port:
        source_port = next((port for port in outputs if _compatible(str(port["type"]), target_port)), None)
    elif not source_port and not target_port:
        for candidate_out in outputs:
            candidate_in = next((port for port in inputs if _compatible(str(candidate_out["type"]), port)), None)
            if candidate_in:
                source_port, target_port = candidate_out, candidate_in
                break
    return source_port, target_port


def validate_workflow(graph: WorkflowGraph, *, for_execution: bool = False) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    nodes = {node.id: node for node in graph.nodes}
    for node in graph.nodes:
        if not _NODE_ID_RE.match(node.id):
            errors.append({"code": "INVALID_NODE_ID", "node_id": node.id, "message": "ID contém caracteres inválidos"})
        if node.id in node_ids:
            errors.append({"code": "DUPLICATE_NODE", "node_id": node.id, "message": "ID de nó duplicado"})
        node_ids.add(node.id)
        if node.type not in CATALOG_BY_TYPE:
            errors.append({"code": "UNKNOWN_NODE_TYPE", "node_id": node.id, "message": f"Tipo desconhecido: {node.type}"})

    edge_ids: set[str] = set()
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree: dict[str, int] = {node_id: 0 for node_id in node_ids}
    cycle_outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    cycle_indegree: dict[str, int] = {node_id: 0 for node_id in node_ids}
    bindings: dict[str, dict[str, Any]] = {}
    input_counts: dict[tuple[str, str], int] = {}
    for edge in graph.edges:
        if edge.id in edge_ids:
            errors.append({"code": "DUPLICATE_EDGE", "edge_id": edge.id, "message": "ID de conexão duplicado"})
        edge_ids.add(edge.id)
        if edge.source not in nodes or edge.target not in nodes:
            errors.append({"code": "DANGLING_EDGE", "edge_id": edge.id, "message": "Conexão aponta para nó inexistente"})
            continue
        if edge.source == edge.target:
            errors.append({"code": "SELF_EDGE", "edge_id": edge.id, "message": "Nó não pode conectar em si mesmo"})
            continue
        # Cycle detection is structural. Even an edge with an invalid port still
        # participates in the graph cycle and must not hide a loop from the user.
        cycle_outgoing[edge.source].append(edge.target)
        cycle_indegree[edge.target] += 1
        source_port, target_port = _resolve_binding(edge, nodes[edge.source], nodes[edge.target])
        if not source_port:
            errors.append({"code": "SOURCE_PORT_INVALID", "edge_id": edge.id, "message": f"Saída inexistente/incompatível: {edge.source_handle or 'auto'}"})
            continue
        if not target_port:
            errors.append({"code": "TARGET_PORT_INVALID", "edge_id": edge.id, "message": f"Entrada inexistente/incompatível: {edge.target_handle or 'auto'}"})
            continue
        if not _compatible(str(source_port["type"]), target_port):
            errors.append({"code": "PORT_TYPE_MISMATCH", "edge_id": edge.id, "message": f"{source_port['type']} não conecta em {target_port['type']}"})
            continue
        key = (edge.target, str(target_port["id"]))
        input_counts[key] = input_counts.get(key, 0) + 1
        if input_counts[key] > 1 and not bool(target_port.get("multiple")):
            errors.append({"code": "INPUT_MULTIPLICITY", "edge_id": edge.id, "message": f"Entrada {target_port['id']} aceita somente uma conexão"})
            continue
        bindings[edge.id] = {
            "source_handle": source_port["id"], "target_handle": target_port["id"],
            "source_type": source_port["type"], "target_type": target_port["type"],
        }
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1

    queue = sorted([node_id for node_id, degree in indegree.items() if degree == 0])
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
                queue.sort()
    cycle_queue = sorted([node_id for node_id, degree in cycle_indegree.items() if degree == 0])
    cycle_order: list[str] = []
    while cycle_queue:
        current = cycle_queue.pop(0)
        cycle_order.append(current)
        for target in cycle_outgoing[current]:
            cycle_indegree[target] -= 1
            if cycle_indegree[target] == 0:
                cycle_queue.append(target)
                cycle_queue.sort()
    if len(cycle_order) != len(nodes):
        errors.append({"code": "WORKFLOW_CYCLE", "message": "O workflow contém ciclo"})

    if for_execution:
        if not graph.nodes:
            errors.append({"code": "EMPTY_WORKFLOW", "message": "Adicione pelo menos um nó antes de executar"})
        for node in graph.nodes:
            if node.type not in CATALOG_BY_TYPE:
                continue
            for port in _ports(node.type, "inputs"):
                if not port.get("required"):
                    continue
                count = input_counts.get((node.id, str(port["id"])), 0)
                fallback = port.get("config_key")
                fallback_value = node.config.get(str(fallback)) if fallback else None
                if count == 0 and fallback_value in (None, "", [], {}):
                    errors.append({
                        "code": "REQUIRED_INPUT_MISSING", "node_id": node.id, "port": port["id"],
                        "message": f"Entrada obrigatória não conectada: {port['label']}",
                    })

    terminal = sorted(node_id for node_id in node_ids if not outgoing[node_id])
    if graph.nodes and not terminal:
        warnings.append({"code": "NO_TERMINAL_NODE", "message": "Nenhum nó terminal encontrado"})
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "order": order,
        "terminal_nodes": terminal,
        "bindings": bindings,
    }


ProgressCallback = Callable[[float, str], Awaitable[None]]
LogCallback = Callable[[str, str], Awaitable[None]]
CancelCheck = Callable[[], bool]


@dataclass(slots=True)
class ExecutionResult:
    node_results: dict[str, Any]
    terminal_results: list[Any]
    assets: list[dict[str, Any]]


class WorkflowExecutor:
    def __init__(self, store: Store, config: AppConfig, registry: EngineRegistry):
        self.store = store
        self.config = config
        self.registry = registry

    @staticmethod
    def _upstream(
        graph: WorkflowGraph,
        node_id: str,
        results: dict[str, dict[str, Any]],
        bindings: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for edge in graph.edges:
            if edge.target != node_id or edge.source not in results:
                continue
            value = dict(results[edge.source])
            binding = bindings.get(edge.id) or {}
            value["_edge"] = {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "source_handle": binding.get("source_handle") or edge.source_handle,
                "target_handle": binding.get("target_handle") or edge.target_handle,
            }
            values.append(value)
        return values

    @staticmethod
    def _values_for_port(upstream: list[dict[str, Any]], port: str) -> list[dict[str, Any]]:
        return [item for item in upstream if (item.get("_edge") or {}).get("target_handle") == port]

    @staticmethod
    def _first_text(upstream: list[dict[str, Any]], fallback: str = "", port: str | None = None) -> str:
        candidates = WorkflowExecutor._values_for_port(upstream, port) if port else upstream
        for item in candidates:
            if item.get("kind") == "text" and str(item.get("text", "")).strip():
                return str(item["text"]).strip()
        return fallback.strip()

    @staticmethod
    def _texts(upstream: list[dict[str, Any]], port: str | None = None) -> list[str]:
        candidates = WorkflowExecutor._values_for_port(upstream, port) if port else upstream
        return [str(item["text"]).strip() for item in candidates if item.get("kind") == "text" and str(item.get("text", "")).strip()]

    @staticmethod
    def _first_path(upstream: list[dict[str, Any]], kinds: set[str], port: str | None = None) -> Path | None:
        candidates = WorkflowExecutor._values_for_port(upstream, port) if port else upstream
        for item in candidates:
            if item.get("kind") in kinds and item.get("path"):
                return Path(str(item["path"])).resolve()
        return None

    @staticmethod
    def _paths(upstream: list[dict[str, Any]], kinds: set[str], port: str | None = None) -> list[Path]:
        candidates = WorkflowExecutor._values_for_port(upstream, port) if port else upstream
        return [Path(str(item["path"])).resolve() for item in candidates if item.get("kind") in kinds and item.get("path")]

    @staticmethod
    def _references(upstream: list[dict[str, Any]], ports: set[str] | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in upstream:
            target_handle = str((item.get("_edge") or {}).get("target_handle") or "")
            if ports and target_handle not in ports:
                continue
            if item.get("kind") == "references":
                candidates = item.get("references") or []
            elif item.get("path") and item.get("kind") in MEDIA_TYPES:
                role = target_handle if target_handle in REFERENCE_ROLES else str(item.get("role") or "reference")
                candidates = [{"path": item["path"], "role": role, "weight": 1.0, "asset_id": (item.get("asset") or {}).get("id")}]
            else:
                candidates = []
            for candidate in candidates:
                path = str(candidate.get("path") or "")
                role = str(candidate.get("role") or "reference")
                key = (path, role)
                if path and key not in seen:
                    seen.add(key)
                    result.append({
                        "path": path,
                        "role": role,
                        "weight": float(candidate.get("weight", 1.0)),
                        "note": str(candidate.get("note") or ""),
                        "asset_id": candidate.get("asset_id"),
                    })
        return result

    @staticmethod
    def _asset_kind(path: Path, fallback: str = "file") -> str:
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".exr"}:
            return "image"
        if suffix in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
            return "video"
        if suffix in {".wav", ".mp3", ".flac", ".aac", ".ogg", ".m4a"}:
            return "audio"
        if suffix in {".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usdz"}:
            return "mesh"
        return fallback

    def _register(
        self,
        path: Path,
        kind: str,
        project_id: str | None,
        job_id: str,
        node: WorkflowNode,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.add_asset(
            path.resolve(), kind, project_id, job_id,
            metadata={"node_id": node.id, "node_type": node.type, **(metadata or {})},
        )

    async def execute(
        self,
        job_id: str,
        project_id: str | None,
        graph: WorkflowGraph,
        *,
        progress: ProgressCallback,
        log: LogCallback,
        cancel_check: CancelCheck,
    ) -> ExecutionResult:
        validation = validate_workflow(graph, for_execution=True)
        if not validation["valid"]:
            raise WorkflowValidationError(validation["errors"])
        output_dir = self.config.outputs_dir / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        nodes = {node.id: node for node in graph.nodes}
        results: dict[str, dict[str, Any]] = {}
        assets: list[dict[str, Any]] = []
        order: list[str] = validation["order"]
        for index, node_id in enumerate(order):
            if cancel_check():
                raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
            node = nodes[node_id]
            await progress(index / max(1, len(order)) * 100.0, node_id)
            await log("info", f"Executando {node.type} ({node.id})")
            upstream = self._upstream(graph, node.id, results, validation["bindings"])
            result = await self._execute_node(node, upstream, output_dir, job_id, project_id, cancel_check=cancel_check, log=log)
            results[node.id] = result
            for asset in result.get("assets") or ([result["asset"]] if result.get("asset") else []):
                assets.append(asset)
        await progress(100.0, "")
        terminal_results = [results[node_id] for node_id in validation["terminal_nodes"] if node_id in results]
        return ExecutionResult(results, terminal_results, assets)

    async def _execute_node(
        self,
        node: WorkflowNode,
        upstream: list[dict[str, Any]],
        output_dir: Path,
        job_id: str,
        project_id: str | None,
        *,
        cancel_check: CancelCheck,
        log: LogCallback,
    ) -> dict[str, Any]:
        config = dict(node.config)

        async def engine_log(stream: str, line: str) -> None:
            await log(stream, line)

        runtime = {"cancel_check": cancel_check, "log": engine_log}
        safe = sanitize_filename(node.id)

        if node.type == "input.text":
            text = str(config.get("text", "")).strip()
            if not text:
                raise EngineExecutionError("PROMPT_EMPTY", f"O nó {node.id} não contém texto")
            return {"kind": "text", "text": text}

        if node.type == "input.asset":
            asset_id = str(config.get("asset_id", "")).strip()
            if not asset_id:
                raise EngineExecutionError("ASSET_ID_MISSING", f"O nó {node.id} não possui asset_id")
            asset = self.store.get_asset(asset_id)
            path = Path(asset["path"]).resolve()
            if not path.is_file():
                raise EngineExecutionError("ASSET_FILE_MISSING", "O arquivo do asset não existe", str(path))
            kind = str(asset.get("kind") or self._asset_kind(path))
            return {"kind": kind, "path": str(path), "asset": asset}

        if node.type == "input.references":
            selected = config.get("references") or []
            if not isinstance(selected, list) or not selected:
                raise EngineExecutionError("REFERENCE_INPUT_MISSING", "Adicione pelo menos uma referência")
            references: list[dict[str, Any]] = []
            for item in selected:
                if not isinstance(item, dict) or not item.get("asset_id"):
                    raise EngineExecutionError("REFERENCE_INVALID", "Referência precisa de asset_id e role", json.dumps(item, ensure_ascii=False))
                asset = self.store.get_asset(str(item["asset_id"]))
                path = Path(asset["path"]).resolve()
                if not path.is_file():
                    raise EngineExecutionError("REFERENCE_FILE_MISSING", "Arquivo de referência não existe", str(path))
                references.append({
                    "asset_id": asset["id"], "path": str(path),
                    "role": str(item.get("role") or "reference"),
                    "weight": float(item.get("weight", 1.0)), "note": str(item.get("note") or ""),
                })
            return {"kind": "references", "references": references, "count": len(references)}

        if node.type in {"llm.enhance", "agent.director"}:
            prompt = self._first_text(upstream, str(config.get("prompt", "")), "brief" if node.type == "agent.director" else "prompt")
            if node.type == "agent.director":
                context = self._texts(upstream, "context")
                if context:
                    prompt = prompt + "\n\nCONTEXTO DAS REFERÊNCIAS:\n" + "\n\n".join(context)
            if not prompt:
                raise EngineExecutionError("PROMPT_INPUT_MISSING", "Conecte um brief/prompt ao agente")
            text = await self.registry.enhance_prompt(prompt, config, **runtime)
            return {"kind": "text", "text": text, "source_prompt": prompt, "provider": config.get("provider")}

        if node.type == "vision.analyze":
            prompt = self._first_text(upstream, str(config.get("prompt", "")), "question")
            references = self._references(upstream, {"references"})
            if not references:
                raise EngineExecutionError("REFERENCE_INPUT_MISSING", "Conecte referências ao nó de visão")
            text = await self.registry.vision(prompt, references, config, **runtime)
            return {"kind": "text", "text": text, "references": references, "provider": config.get("provider")}

        if node.type == "prompt.compose":
            parts = self._texts(upstream, "parts")
            if not parts:
                raise EngineExecutionError("PROMPT_INPUT_MISSING", "Conecte textos para compor")
            separator = str(config.get("separator", "\n\n"))
            text = str(config.get("prefix", "")) + separator.join(parts) + str(config.get("suffix", ""))
            return {"kind": "text", "text": text.strip(), "parts": len(parts)}

        if node.type in {"image.generate", "image.edit"}:
            prompt = self._first_text(upstream, str(config.get("prompt", "")), "prompt")
            if not prompt:
                raise EngineExecutionError("PROMPT_INPUT_MISSING", "Conecte uma instrução ao nó de imagem")
            # `_references` already preserves the direct image/mask port role and
            # de-duplicates each (path, role). Do not append those inputs twice.
            references = self._references(upstream, {"references", "image", "mask"})
            output = output_dir / f"{safe}.png"
            generated = await self.registry.generate_image(
                prompt, str(config.get("negative_prompt", "")), output, config,
                references=references, operation="image_edit" if node.type == "image.edit" else "image", **runtime,
            )
            actual = Path(generated["path"]).resolve()
            asset = self._register(actual, "image", project_id, job_id, node, {"provider": config.get("provider") or config.get("engine"), "model": config.get("model"), "profile_id": config.get("profile_id")})
            return {"kind": "image", "path": str(actual), "asset": asset, "engine_result": generated, "references": references}

        if node.type == "image.upscale":
            source = self._first_path(upstream, {"image", "media"}, "image")
            if not source:
                raise EngineExecutionError("IMAGE_INPUT_MISSING", "Conecte uma imagem ao upscale")
            output = output_dir / f"{safe}-upscaled.png"
            generated = await self.registry.postprocess().upscale_image(source, output, scale=int(config.get("scale", 4)), model=str(config.get("model", "realesrgan-x4plus")), tile=int(config.get("tile", 0)), **runtime)
            asset = self._register(output, "image", project_id, job_id, node, {"operation": "ai_upscale", "scale": config.get("scale", 4)})
            return {"kind": "image", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "image.resize":
            source = self._first_path(upstream, {"image", "media"}, "image")
            if not source:
                raise EngineExecutionError("IMAGE_INPUT_MISSING", "Conecte uma imagem ao resize")
            output = output_dir / f"{safe}-resized.png"
            generated = await self.registry.postprocess().resize_image_ffmpeg(source, output, int(config.get("width", 3840)), int(config.get("height", 2160)), **runtime)
            asset = self._register(output, "image", project_id, job_id, node, {"operation": "lanczos_resize", "width": config.get("width"), "height": config.get("height")})
            return {"kind": "image", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type in {"video.generate", "video.first_last", "video.reference"}:
            prompt = self._first_text(upstream, str(config.get("prompt", "")), "prompt")
            if not prompt:
                raise EngineExecutionError("PROMPT_INPUT_MISSING", "Conecte um prompt ao gerador de vídeo")
            references = self._references(upstream, {"references", "start_frame", "end_frame"})
            if node.type == "video.first_last":
                start = self._first_path(upstream, {"image", "media"}, "start_frame")
                end = self._first_path(upstream, {"image", "media"}, "end_frame")
                if not start or not end:
                    raise EngineExecutionError("FIRST_LAST_FRAME_MISSING", "Conecte start frame e end frame")
                references = [item for item in references if item.get("role") not in {"start_frame", "end_frame"}]
                references.insert(0, {"path": str(start), "role": "start_frame", "weight": 1.0})
                references.insert(1, {"path": str(end), "role": "end_frame", "weight": 1.0})
            if node.type == "video.reference" and not references:
                raise EngineExecutionError("REFERENCE_INPUT_MISSING", "Vídeo multirreferência precisa de referências")
            output = output_dir / f"{safe}.mp4"
            generated = await self.registry.generate_video(prompt, str(config.get("negative_prompt", "")), output, config, references=references, **runtime)
            actual = Path(generated["path"]).resolve()
            asset = self._register(actual, "video", project_id, job_id, node, {"provider": config.get("provider") or config.get("engine"), "model": config.get("model"), "profile_id": config.get("profile_id")})
            return {"kind": "video", "path": str(actual), "asset": asset, "engine_result": generated, "references": references}

        if node.type == "video.extract_frame":
            source = self._first_path(upstream, {"video", "media"}, "video")
            if not source:
                raise EngineExecutionError("VIDEO_INPUT_MISSING", "Conecte um vídeo")
            output = output_dir / f"{safe}.png"
            generated = await self.registry.postprocess().extract_frame(source, output, at_seconds=float(config.get("at_seconds", 0.0)), **runtime)
            asset = self._register(output, "image", project_id, job_id, node, {"operation": "extract_frame", "at_seconds": config.get("at_seconds", 0.0)})
            return {"kind": "image", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "video.concat":
            sources = self._paths(upstream, {"video", "media"}, "videos")
            if len(sources) < 2:
                raise EngineExecutionError("VIDEO_INPUT_MISSING", "Conecte ao menos dois vídeos")
            output = output_dir / f"{safe}.mp4"
            generated = await self.registry.postprocess().concat_videos(sources, output, transition_seconds=float(config.get("transition_seconds", 0.0)), **runtime)
            asset = self._register(output, "video", project_id, job_id, node, {"operation": "concat", "count": len(sources)})
            return {"kind": "video", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "video.resize":
            source = self._first_path(upstream, {"video", "media"}, "video")
            if not source:
                raise EngineExecutionError("VIDEO_INPUT_MISSING", "Conecte um vídeo ao resize")
            output = output_dir / f"{safe}-resized.mp4"
            generated = await self.registry.postprocess().resize_video_ffmpeg(
                source, output, int(config.get("width", 3840)), int(config.get("height", 2160)),
                codec=str(config.get("codec", "h265")), crf=int(config.get("crf", 16)), **runtime,
            )
            asset = self._register(output, "video", project_id, job_id, node, {"operation": "lanczos_resize", "width": config.get("width"), "height": config.get("height")})
            return {"kind": "video", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "video.interpolate":
            source = self._first_path(upstream, {"video", "media"}, "video")
            if not source:
                raise EngineExecutionError("VIDEO_INPUT_MISSING", "Conecte um vídeo à interpolação")
            output = output_dir / f"{safe}-interpolated.mp4"
            generated = await self.registry.postprocess().interpolate_video(source, output, target_fps=int(config.get("target_fps", 60)), engine=str(config.get("engine", "rife")), **runtime)
            asset = self._register(output, "video", project_id, job_id, node, {"operation": "interpolate", "target_fps": config.get("target_fps", 60)})
            return {"kind": "video", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "video.upscale":
            source = self._first_path(upstream, {"video", "media"}, "video")
            if not source:
                raise EngineExecutionError("VIDEO_INPUT_MISSING", "Conecte um vídeo ao upscale")
            output = output_dir / f"{safe}-upscaled.mp4"
            work_dir = output_dir / f".{safe}-frames"
            generated = await self.registry.postprocess().upscale_video(source, output, work_dir, scale=int(config.get("scale", 2)), model=str(config.get("model", "realesrgan-x4plus")), target_fps=int(config.get("target_fps", 24)), **runtime)
            asset = self._register(output, "video", project_id, job_id, node, {"operation": "ai_video_upscale", "scale": config.get("scale", 2)})
            return {"kind": "video", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "mesh.generate":
            prompt = self._first_text(upstream, str(config.get("prompt", "")), "prompt")
            references = self._references(upstream, {"references"})
            if not prompt and not references:
                raise EngineExecutionError("MESH_INPUT_MISSING", "Forneça texto ou imagens para geração 3D")
            output = output_dir / f"{safe}.glb"
            generated = await self.registry.generate_mesh(prompt, str(config.get("negative_prompt", "")), references, output, config, **runtime)
            actual = Path(generated["path"]).resolve()
            asset = self._register(actual, "mesh", project_id, job_id, node, {"provider": config.get("provider"), "model": config.get("model"), "references": len(references)})
            return {"kind": "mesh", "path": str(actual), "asset": asset, "engine_result": generated, "references": references}

        if node.type == "mesh.preview":
            source = self._first_path(upstream, {"mesh", "media"}, "mesh")
            if not source:
                raise EngineExecutionError("MESH_INPUT_MISSING", "Conecte um modelo 3D")
            output = output_dir / f"{safe}.mp4"
            generated = await self.registry.mesh().turntable(source, output, config, **runtime)
            asset = self._register(output, "video", project_id, job_id, node, {"operation": "mesh_turntable", "source": str(source)})
            return {"kind": "video", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "mesh.export":
            source = self._first_path(upstream, {"mesh", "media"}, "mesh")
            if not source:
                raise EngineExecutionError("MESH_INPUT_MISSING", "Conecte um modelo 3D")
            fmt = str(config.get("format", "glb")).lower()
            filename = sanitize_filename(str(config.get("filename") or f"modelo-final.{fmt}"), f"modelo-final.{fmt}")
            output = (output_dir / Path(filename).stem).with_suffix(f".{fmt}")
            if source.suffix.lower() == output.suffix.lower():
                shutil.copy2(source, output)
                generated = {"path": str(output), "engine": "copy", "source": str(source)}
            else:
                generated = await self.registry.mesh().convert(source, output, **runtime)
            asset = self._register(output, "mesh", project_id, job_id, node, {"operation": "mesh_export", "format": fmt})
            return {"kind": "mesh", "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "media.export":
            if not upstream:
                raise EngineExecutionError("MEDIA_INPUT_MISSING", "Conecte mídia à exportação")
            source_item = self._values_for_port(upstream, "media")[-1] if self._values_for_port(upstream, "media") else upstream[-1]
            source = Path(str(source_item.get("path") or "")).resolve() if source_item.get("path") else None
            if not source or not source.is_file():
                raise EngineExecutionError("MEDIA_INPUT_MISSING", "A entrada não contém arquivo exportável")
            kind = str(source_item.get("kind") or self._asset_kind(source))
            filename = sanitize_filename(str(config.get("filename") or source.name), source.name)
            if kind == "video":
                suffix = ".mov" if str(config.get("codec", "h265")) == "prores" else ".mp4"
                output = output_dir / (Path(filename).stem + suffix)
                generated = await self.registry.postprocess().export_media(source, output, codec=str(config.get("codec", "h265")), crf=int(config.get("crf", 16)), fps=int(config.get("fps")) if int(config.get("fps", 0) or 0) > 0 else None, **runtime)
            else:
                output = output_dir / filename
                if output.suffix.lower() != source.suffix.lower():
                    output = output.with_suffix(source.suffix)
                shutil.copy2(source, output)
                generated = {"path": str(output), "engine": "copy", "source": str(source)}
            final_kind = self._asset_kind(output, kind)
            asset = self._register(output, final_kind, project_id, job_id, node, {"operation": "export", "codec": config.get("codec")})
            return {"kind": final_kind, "path": str(output), "asset": asset, "engine_result": generated}

        if node.type == "output.preview":
            if not upstream:
                raise EngineExecutionError("MEDIA_INPUT_MISSING", "Conecte um resultado ao preview")
            value = dict(upstream[-1])
            value.pop("_edge", None)
            return value

        raise EngineExecutionError("NODE_NOT_IMPLEMENTED", f"Nó não implementado: {node.type}")
