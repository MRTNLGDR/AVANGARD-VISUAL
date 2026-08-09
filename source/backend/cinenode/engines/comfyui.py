from __future__ import annotations

import asyncio
import copy
import json
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .common import EngineExecutionError


def _replace_tokens(value: Any, tokens: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_tokens(item, tokens) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_tokens(item, tokens) for item in value]
    if isinstance(value, str):
        if value in tokens:
            return tokens[value]
        result = value
        for token, replacement in tokens.items():
            result = result.replace(token, str(replacement))
        return result
    return value


class ComfyUIEngine:
    engine_id = "comfyui"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.base_url = str(settings.get("base_url", "http://127.0.0.1:8188")).rstrip("/")

    async def upload_input(self, path: Path, *, subfolder: str = "cinenode") -> str:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise EngineExecutionError("REFERENCE_FILE_MISSING", "Arquivo de referência não existe", str(path))

        configured_input = str(self.settings.get("input_dir") or "").strip()
        if configured_input:
            input_root = Path(configured_input).expanduser().resolve()
            target_dir = input_root / subfolder
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{uuid.uuid4().hex[:10]}-{path.name}"
            shutil.copy2(path, target)
            return f"{subfolder}/{target.name}".replace("\\", "/")

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with path.open("rb") as stream:
                    response = await client.post(
                        f"{self.base_url}/upload/image",
                        files={"image": (path.name, stream, mime)},
                        data={"type": "input", "subfolder": subfolder, "overwrite": "true"},
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise EngineExecutionError("COMFYUI_UPLOAD_FAILED", "Falha ao enviar referência para o diretório de entrada do ComfyUI", str(exc)) from exc
        name = str(payload.get("name") or "").strip()
        returned_subfolder = str(payload.get("subfolder") or subfolder).strip().strip("/\\")
        if not name:
            raise EngineExecutionError("COMFYUI_INVALID_RESPONSE", "ComfyUI não retornou o nome do arquivo enviado", json.dumps(payload)[:1000])
        return f"{returned_subfolder}/{name}" if returned_subfolder else name

    async def upload_inputs(self, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        for item in references:
            path = Path(str(item.get("path") or ""))
            remote_name = await self.upload_input(path)
            uploaded.append({**item, "local_path": str(path.resolve()), "path": remote_name})
        return uploaded

    async def status(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                response.raise_for_status()
                data = response.json()
            return {"engine_id": self.engine_id, "available": True, "version": str(data.get("system", {}).get("comfyui_version", "unknown")), "detail": self.base_url}
        except Exception as exc:
            return {"engine_id": self.engine_id, "available": False, "version": None, "detail": str(exc)}

    async def execute_workflow(
        self,
        workflow: dict[str, Any],
        output_dir: Path,
        tokens: dict[str, Any],
        *,
        cancel_check=None,
        progress_callback=None,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        client_id = uuid.uuid4().hex
        prompt = _replace_tokens(copy.deepcopy(workflow), tokens)
        timeout = float(self.settings.get("timeout_seconds", 14400))
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(f"{self.base_url}/prompt", json={"prompt": prompt, "client_id": client_id})
                response.raise_for_status()
                prompt_id = response.json().get("prompt_id")
            if not prompt_id:
                raise EngineExecutionError("COMFYUI_INVALID_RESPONSE", "ComfyUI não retornou prompt_id")
            started = asyncio.get_running_loop().time()
            while True:
                if cancel_check and cancel_check():
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(f"{self.base_url}/interrupt")
                    raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
                if asyncio.get_running_loop().time() - started > timeout:
                    raise EngineExecutionError("ENGINE_TIMEOUT", "ComfyUI excedeu o limite de tempo")
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(f"{self.base_url}/history/{prompt_id}")
                    response.raise_for_status()
                    history = response.json()
                entry = history.get(prompt_id)
                if entry:
                    outputs = entry.get("outputs") or {}
                    downloaded: list[Path] = []
                    for node_output in outputs.values():
                        for media_key in ("images", "gifs", "videos", "audio"):
                            for item in node_output.get(media_key, []) or []:
                                filename = item.get("filename")
                                if not filename:
                                    continue
                                query = urlencode({
                                    "filename": filename,
                                    "subfolder": item.get("subfolder", ""),
                                    "type": item.get("type", "output"),
                                })
                                async with httpx.AsyncClient(timeout=120) as client:
                                    media = await client.get(f"{self.base_url}/view?{query}")
                                    media.raise_for_status()
                                target = output_dir / Path(filename).name
                                target.write_bytes(media.content)
                                downloaded.append(target)
                    if not downloaded:
                        raise EngineExecutionError("COMFYUI_OUTPUT_MISSING", "ComfyUI concluiu sem arquivos de saída", json.dumps(entry)[:2000])
                    return downloaded
                if progress_callback:
                    await progress_callback(None)
                await asyncio.sleep(1)
        except httpx.HTTPError as exc:
            raise EngineExecutionError("COMFYUI_REQUEST_FAILED", "Falha ao comunicar com ComfyUI", str(exc)) from exc
