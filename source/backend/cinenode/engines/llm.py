from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from .common import EngineExecutionError, LogCallback, CancelCheck, find_executable, require_executable, require_file, run_command


class LocalLLMEngine:
    def __init__(self, ollama: dict[str, Any], opencode: dict[str, Any]):
        self.ollama = dict(ollama or {})
        self.opencode = dict(opencode or {})

    async def status(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        base = str(self.ollama.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{base}/api/version")
                response.raise_for_status()
                version = response.json().get("version", "unknown")
            result.append({"engine_id": "ollama", "available": True, "version": version, "detail": base})
        except Exception as exc:
            result.append({"engine_id": "ollama", "available": False, "version": None, "detail": str(exc)})
        executable = find_executable(self.opencode.get("binary_path", "opencode"))
        result.append({
            "engine_id": "opencode",
            "available": bool(executable),
            "version": "installed" if executable else None,
            "detail": executable or "opencode não encontrado",
        })
        return result

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.35,
    ) -> str:
        base = str(self.ollama.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        selected = model or self.ollama.get("model")
        if not selected:
            raise EngineExecutionError("LLM_MODEL_MISSING", "Nenhum modelo Ollama foi configurado")
        payload: dict[str, Any] = {
            "model": selected,
            "stream": False,
            "messages": messages,
            "options": {"temperature": temperature, "num_ctx": int(self.ollama.get("num_ctx", 16384))},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=float(self.ollama.get("timeout_seconds", 600))) as client:
                response = await client.post(f"{base}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise EngineExecutionError("OLLAMA_REQUEST_FAILED", "Falha ao consultar o Ollama local", str(exc)) from exc
        output = str((data.get("message") or {}).get("content") or "").strip()
        if not output:
            raise EngineExecutionError("LLM_EMPTY_RESPONSE", "Ollama não retornou texto", json.dumps(data)[:1000])
        return output

    async def enhance(
        self,
        prompt: str,
        *,
        provider: str = "ollama",
        model: str | None = None,
        instruction: str | None = None,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> str:
        instruction = instruction or (
            "Aprimore o prompt para geração audiovisual. Preserve intenção, identidade dos personagens, "
            "continuidade entre planos e todas as restrições. Retorne somente o prompt final."
        )
        if provider == "opencode":
            executable = require_executable(self.opencode.get("binary_path", "opencode"), "opencode")
            selected = model or self.opencode.get("model")
            args = [executable, "run"]
            if selected:
                args.extend(["--model", str(selected)])
            args.append(f"{instruction}\n\nPROMPT ORIGINAL:\n{prompt}")
            result = await run_command(
                args,
                timeout=int(self.opencode.get("timeout_seconds", 900)),
                cancel_check=cancel_check,
                log=log,
            )
            output = result.stdout.strip()
            if not output:
                raise EngineExecutionError("LLM_EMPTY_RESPONSE", "OpenCode não retornou texto")
            return output
        return await self.chat(
            [
                {"role": "system", "content": instruction},
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=0.45,
        )

    async def vision(
        self,
        image_paths: list[Path],
        prompt: str,
        *,
        model: str | None = None,
    ) -> str:
        if not image_paths:
            raise EngineExecutionError("REFERENCE_INPUT_MISSING", "O nó de visão precisa de ao menos uma imagem")
        images: list[str] = []
        for path in image_paths:
            verified = require_file(str(path), "vision_reference")
            if verified.stat().st_size > 30 * 1024 * 1024:
                raise EngineExecutionError("REFERENCE_TOO_LARGE", "Imagem para Ollama VLM excede 30 MB", str(verified))
            images.append(base64.b64encode(verified.read_bytes()).decode("ascii"))
        selected = model or self.ollama.get("vision_model") or self.ollama.get("model")
        return await self.chat(
            [
                {
                    "role": "user",
                    "content": prompt or "Descreva estas referências com precisão para recriação visual e continuidade cinematográfica.",
                    "images": images,
                }
            ],
            model=str(selected) if selected else None,
            temperature=0.2,
        )
