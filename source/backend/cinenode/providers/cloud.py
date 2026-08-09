from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import httpx

from ..engines.common import EngineExecutionError
from ..media import download_output, extract_urls, file_to_data_uri, first_output_url

CancelCheck = Callable[[], bool] | None


def _env_secret(settings: dict[str, Any], default_env: str) -> str:
    env_name = str(settings.get("api_key_env") or default_env)
    value = os.getenv(env_name, "").strip()
    if not value:
        raise EngineExecutionError(
            "PROVIDER_API_KEY_MISSING",
            f"A chave do provider não está configurada no ambiente ({env_name}).",
            f"Defina {env_name} antes de iniciar o aplicativo; a chave não é salva no banco.",
        )
    return value


def _join(base: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return base.rstrip("/") + "/" + path.lstrip("/")


def _json_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("detail") or payload.get("error") or payload
            return json.dumps(detail, ensure_ascii=False)[:3000]
        return json.dumps(payload, ensure_ascii=False)[:3000]
    except Exception:
        return response.text[-3000:]


async def _sleep_or_cancel(seconds: float, cancel_check: CancelCheck) -> None:
    steps = max(1, int(seconds / 0.2))
    for _ in range(steps):
        if cancel_check and cancel_check():
            raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
        await asyncio.sleep(seconds / steps)


class HttpProvider:
    provider_id = "cloud.base"
    default_env = ""

    def __init__(self, settings: dict[str, Any]):
        self.settings = dict(settings or {})
        self.timeout_seconds = int(self.settings.get("timeout_seconds", 1800))
        self.poll_interval = max(0.1, float(self.settings.get("poll_interval_seconds", 2.0)))
        self.allow_private = bool(self.settings.get("allow_private_output_urls", False))

    def key(self) -> str:
        return _env_secret(self.settings, self.default_env)

    def client(self, headers: dict[str, str]) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(30.0, float(self.timeout_seconds)))
        return httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True)

    @staticmethod
    async def ensure_success(response: httpx.Response, code: str = "PROVIDER_REQUEST_FAILED") -> dict[str, Any]:
        if response.status_code >= 400:
            raise EngineExecutionError(
                code,
                f"Provider retornou HTTP {response.status_code}.",
                _json_error(response),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EngineExecutionError(code, "Provider retornou JSON inválido", response.text[-3000:]) from exc
        if not isinstance(payload, dict):
            raise EngineExecutionError(code, "Provider retornou payload inesperado", str(payload)[:3000])
        return payload

    async def materialize(self, payload: Any, output_path: Path) -> dict[str, Any]:
        url = first_output_url(payload)
        result = await download_output(
            url,
            output_path,
            max_bytes=int(self.settings.get("max_output_bytes", 8 * 1024**3)),
            timeout_seconds=self.timeout_seconds,
            allow_private=self.allow_private,
        )
        return {**result, "provider": self.provider_id, "provider_payload": payload, "output_url": url}


class FreepikProvider(HttpProvider):
    provider_id = "cloud.freepik"
    default_env = "FREEPIK_API_KEY"

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self.base_url = str(settings.get("base_url") or "https://api.freepik.com/v1/ai").rstrip("/")

    def headers(self) -> dict[str, str]:
        return {"x-freepik-api-key": self.key(), "Content-Type": "application/json"}

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise EngineExecutionError("PROVIDER_RESPONSE_INVALID", "Freepik retornou data inválido", str(payload)[:3000])
        return data

    async def _submit_and_poll(self, endpoint: str, payload: dict[str, Any], *, cancel_check: CancelCheck = None) -> dict[str, Any]:
        url = _join(self.base_url, endpoint)
        async with self.client(self.headers()) as client:
            response = await client.post(url, json=payload)
            initial = await self.ensure_success(response)
            data = self._data(initial)
            if extract_urls(data):
                return initial
            task_id = str(data.get("task_id") or data.get("id") or "").strip()
            if not task_id:
                raise EngineExecutionError("PROVIDER_TASK_ID_MISSING", "Freepik não retornou task_id", str(initial)[:3000])
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while True:
                if cancel_check and cancel_check():
                    raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
                if asyncio.get_running_loop().time() >= deadline:
                    raise EngineExecutionError("PROVIDER_TIMEOUT", "A tarefa Freepik excedeu o tempo limite", task_id)
                status_response = await client.get(f"{url.rstrip('/')}/{task_id}")
                status_payload = await self.ensure_success(status_response)
                status_data = self._data(status_payload)
                status = str(status_data.get("status") or "").upper()
                if status in {"COMPLETED", "SUCCEEDED", "SUCCESS", "DONE"}:
                    if not extract_urls(status_data):
                        raise EngineExecutionError("PROVIDER_OUTPUT_MISSING", "Freepik concluiu sem arquivo gerado", str(status_payload)[:3000])
                    return status_payload
                if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                    raise EngineExecutionError(
                        "PROVIDER_TASK_FAILED",
                        f"A tarefa Freepik terminou como {status}.",
                        str(status_data.get("error") or status_data.get("message") or status_payload)[:3000],
                    )
                await _sleep_or_cancel(self.poll_interval, cancel_check)

    @staticmethod
    def _overlay(payload: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        extra = parameters.get("payload")
        if isinstance(extra, dict):
            payload.update(extra)
        for key in ("seed", "aspect_ratio", "resolution", "duration", "fps", "generate_audio", "cfg_scale", "ratio"):
            if key in parameters and parameters[key] not in (None, ""):
                payload[key] = parameters[key]
        return payload

    async def invoke(
        self,
        operation: str,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path | None,
        parameters: dict[str, Any],
        *,
        cancel_check: CancelCheck = None,
    ) -> dict[str, Any]:
        encoded = [
            {**item, "value": file_to_data_uri(Path(str(item["path"])), max_bytes=20 * 1024 * 1024)}
            for item in references
        ]
        model = str(parameters.get("model") or "").strip()
        endpoint = str(parameters.get("endpoint") or "").strip()

        if operation == "enhance_prompt":
            endpoint = endpoint or "/improve-prompt"
            payload = self._overlay({"prompt": prompt, "type": parameters.get("type", "image"), "language": parameters.get("language", "en")}, parameters)
        elif operation == "vision":
            if not encoded:
                raise EngineExecutionError("REFERENCE_INPUT_MISSING", "Image to Prompt precisa de uma imagem")
            endpoint = endpoint or "/image-to-prompt"
            payload = self._overlay({"image": encoded[0]["value"]}, parameters)
        elif operation == "image":
            endpoint = endpoint or f"/text-to-image/{model or 'seedream-v5-lite'}"
            payload = {"prompt": prompt}
            if negative:
                payload["negative_prompt"] = negative
            if encoded:
                # Flux 2 Pro and similar endpoints accept multiple contextual images; a raw payload override remains available.
                payload[str(parameters.get("references_field") or "reference_images")] = [item["value"] for item in encoded[:4]]
            payload = self._overlay(payload, parameters)
        elif operation == "image_edit":
            if not encoded:
                raise EngineExecutionError("REFERENCE_INPUT_MISSING", "Edição de imagem precisa de uma imagem")
            endpoint = endpoint or "/ideogram-image-edit"
            payload = {"prompt": prompt, "image": encoded[0]["value"]}
            mask = next((item for item in encoded if item.get("role") == "mask"), None)
            if mask:
                payload["mask"] = mask["value"]
            style_refs = [item["value"] for item in encoded[1:] if item.get("role") != "mask"]
            if style_refs:
                payload["style_reference_images"] = style_refs
            payload = self._overlay(payload, parameters)
        elif operation == "video":
            start = next((item for item in encoded if item.get("role") == "start_frame"), None)
            end = next((item for item in encoded if item.get("role") == "end_frame"), None)
            general = [item for item in encoded if item.get("role") not in {"start_frame", "end_frame", "mask"}]
            duration = int(parameters.get("duration", 5))
            if start and end:
                endpoint = endpoint or "/image-to-video/kling-std"
                payload = {"prompt": prompt, "image": start["value"], "image_tail": end["value"], "duration": str(duration)}
            elif len(general) > 1:
                endpoint = endpoint or "/image-to-video/kling-o1-std-video-reference"
                payload = {"prompt": prompt, "reference_images": [item["value"] for item in general[:7]], "duration": 10 if duration >= 10 else 5, "aspect_ratio": parameters.get("aspect_ratio", "16:9")}
            elif start or general:
                image = (start or general[0])["value"]
                endpoint = endpoint or f"/image-to-video/{model or 'kling-v2-1-std'}"
                payload = {"prompt": prompt, "image": image, "duration": str(duration)}
            else:
                endpoint = endpoint or f"/text-to-video/{model or 'runway-4-5'}"
                payload = {"prompt": prompt, "duration": duration, "ratio": parameters.get("ratio", parameters.get("aspect_ratio", "16:9"))}
            if negative:
                payload["negative_prompt"] = negative
            payload = self._overlay(payload, parameters)
        else:
            raise EngineExecutionError("PROVIDER_OPERATION_UNSUPPORTED", f"Freepik não suporta a operação {operation}")

        response = await self._submit_and_poll(endpoint, payload, cancel_check=cancel_check)
        if output_path is None:
            data = self._data(response)
            generated = data.get("generated")
            text = ""
            if isinstance(generated, list) and generated and isinstance(generated[0], str) and not generated[0].startswith(("http://", "https://", "data:")):
                text = generated[0]
            elif isinstance(data.get("result"), str):
                text = data["result"]
            return {"provider": self.provider_id, "payload": response, "text": text}
        return await self.materialize(response, output_path)


class ReplicateProvider(HttpProvider):
    provider_id = "cloud.replicate"
    default_env = "REPLICATE_API_TOKEN"

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self.base_url = str(settings.get("base_url") or "https://api.replicate.com/v1").rstrip("/")

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key()}", "Content-Type": "application/json", "Prefer": "wait=60"}

    async def invoke(
        self,
        operation: str,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path,
        parameters: dict[str, Any],
        *,
        cancel_check: CancelCheck = None,
    ) -> dict[str, Any]:
        model = str(parameters.get("model") or "").strip()
        version = str(parameters.get("version") or "").strip()
        if not model and not version:
            raise EngineExecutionError("PROVIDER_MODEL_MISSING", "Informe model (owner/name) ou version para Replicate")
        input_payload = dict(parameters.get("payload") or {})
        input_payload.setdefault(str(parameters.get("prompt_field") or "prompt"), prompt)
        if negative:
            input_payload.setdefault(str(parameters.get("negative_field") or "negative_prompt"), negative)
        encoded = [{**item, "value": file_to_data_uri(Path(str(item["path"])), max_bytes=50 * 1024 * 1024)} for item in references]
        start = next((item for item in encoded if item.get("role") == "start_frame"), None)
        end = next((item for item in encoded if item.get("role") == "end_frame"), None)
        mask = next((item for item in encoded if item.get("role") == "mask"), None)
        general = [item for item in encoded if item.get("role") not in {"start_frame", "end_frame", "mask"}]
        if start:
            input_payload.setdefault(str(parameters.get("start_field") or "image"), start["value"])
        elif general:
            input_payload.setdefault(str(parameters.get("image_field") or "image"), general[0]["value"])
        if end:
            input_payload.setdefault(str(parameters.get("end_field") or "end_image"), end["value"])
        if mask:
            input_payload.setdefault(str(parameters.get("mask_field") or "mask"), mask["value"])
        if len(general) > 1:
            input_payload.setdefault(str(parameters.get("references_field") or "reference_images"), [item["value"] for item in general])
        for key in ("width", "height", "aspect_ratio", "duration", "fps", "seed", "output_format"):
            if key in parameters and parameters[key] not in (None, ""):
                input_payload.setdefault(key, parameters[key])

        if version:
            create_url = f"{self.base_url}/predictions"
            create_body = {"version": version, "input": input_payload}
        else:
            parts = model.split("/")
            if len(parts) != 2 or not all(parts):
                raise EngineExecutionError("PROVIDER_MODEL_INVALID", "Modelo Replicate deve usar owner/name", model)
            create_url = f"{self.base_url}/models/{parts[0]}/{parts[1]}/predictions"
            create_body = {"input": input_payload}

        async with self.client(self.headers()) as client:
            created = await self.ensure_success(await client.post(create_url, json=create_body))
            prediction = created
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while str(prediction.get("status", "")).lower() not in {"succeeded", "failed", "canceled", "cancelled"}:
                if cancel_check and cancel_check():
                    cancel_url = (prediction.get("urls") or {}).get("cancel")
                    if cancel_url:
                        try:
                            await client.post(cancel_url)
                        except httpx.HTTPError:
                            pass
                    raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
                if asyncio.get_running_loop().time() >= deadline:
                    raise EngineExecutionError("PROVIDER_TIMEOUT", "A previsão Replicate excedeu o tempo limite", str(prediction.get("id")))
                get_url = (prediction.get("urls") or {}).get("get") or f"{self.base_url}/predictions/{prediction.get('id')}"
                await _sleep_or_cancel(self.poll_interval, cancel_check)
                prediction = await self.ensure_success(await client.get(get_url))
            status = str(prediction.get("status", "")).lower()
            if status != "succeeded":
                raise EngineExecutionError("PROVIDER_TASK_FAILED", f"Replicate terminou como {status}", str(prediction.get("error") or prediction)[:3000])
        return await self.materialize(prediction.get("output"), output_path)


class FalProvider(HttpProvider):
    provider_id = "cloud.fal"
    default_env = "FAL_KEY"

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self.base_url = str(settings.get("base_url") or "https://queue.fal.run").rstrip("/")

    def headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Key {self.key()}", "Content-Type": "application/json"}
        if self.settings.get("store_io") is False:
            headers["X-Fal-Store-IO"] = "0"
        return headers

    async def invoke(
        self,
        operation: str,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path,
        parameters: dict[str, Any],
        *,
        cancel_check: CancelCheck = None,
    ) -> dict[str, Any]:
        model = str(parameters.get("model") or "").strip()
        if not model:
            raise EngineExecutionError("PROVIDER_MODEL_MISSING", "Informe o endpoint/modelo fal, por exemplo fal-ai/flux/dev")
        payload = dict(parameters.get("payload") or {})
        payload.setdefault(str(parameters.get("prompt_field") or "prompt"), prompt)
        if negative:
            payload.setdefault(str(parameters.get("negative_field") or "negative_prompt"), negative)
        encoded = [{**item, "value": file_to_data_uri(Path(str(item["path"])), max_bytes=50 * 1024 * 1024)} for item in references]
        start = next((item for item in encoded if item.get("role") == "start_frame"), None)
        end = next((item for item in encoded if item.get("role") == "end_frame"), None)
        general = [item for item in encoded if item.get("role") not in {"start_frame", "end_frame", "mask"}]
        if start:
            payload.setdefault(str(parameters.get("start_field") or "image_url"), start["value"])
        elif general:
            payload.setdefault(str(parameters.get("image_field") or "image_url"), general[0]["value"])
        if end:
            payload.setdefault(str(parameters.get("end_field") or "end_image_url"), end["value"])
        if len(general) > 1:
            payload.setdefault(str(parameters.get("references_field") or "reference_images"), [item["value"] for item in general])
        for key in ("image_size", "aspect_ratio", "duration", "fps", "seed", "num_inference_steps"):
            if key in parameters and parameters[key] not in (None, ""):
                payload.setdefault(key, parameters[key])

        submit_url = f"{self.base_url}/{model.lstrip('/')}"
        async with self.client(self.headers()) as client:
            submitted = await self.ensure_success(await client.post(submit_url, json=payload))
            status_url = submitted.get("status_url")
            response_url = submitted.get("response_url")
            cancel_url = submitted.get("cancel_url")
            request_id = submitted.get("request_id")
            if not status_url or not response_url:
                # Some private/local fal-compatible endpoints return the result synchronously.
                if extract_urls(submitted):
                    return await self.materialize(submitted, output_path)
                raise EngineExecutionError("PROVIDER_RESPONSE_INVALID", "fal não retornou status_url/response_url", str(submitted)[:3000])
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while True:
                if cancel_check and cancel_check():
                    if cancel_url:
                        try:
                            await client.put(cancel_url)
                        except httpx.HTTPError:
                            pass
                    raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
                if asyncio.get_running_loop().time() >= deadline:
                    raise EngineExecutionError("PROVIDER_TIMEOUT", "A tarefa fal excedeu o tempo limite", str(request_id))
                status_payload = await self.ensure_success(await client.get(status_url, params={"logs": 1}))
                status = str(status_payload.get("status") or "").upper()
                if status == "COMPLETED":
                    if status_payload.get("error"):
                        raise EngineExecutionError("PROVIDER_TASK_FAILED", "fal concluiu com erro", str(status_payload.get("error"))[:3000])
                    result = await self.ensure_success(await client.get(response_url))
                    return await self.materialize(result, output_path)
                if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                    raise EngineExecutionError("PROVIDER_TASK_FAILED", f"fal terminou como {status}", str(status_payload)[:3000])
                await _sleep_or_cancel(self.poll_interval, cancel_check)


class TripoCloudProvider(HttpProvider):
    """Tripo Platform API v2 adapter.

    This implementation follows the current public contract:
    - upload: POST /upload/sts
    - create: POST /task
    - poll: GET /task/{task_id}
    - multiview order: front, left, back, right
    """

    provider_id = "cloud.tripo"
    default_env = "TRIPO_API_KEY"
    _VIEW_ORDER = ("front", "left", "back", "right")

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self.base_url = str(settings.get("base_url") or "https://api.tripo3d.ai/v2/openapi").rstrip("/")

    def headers(self, *, json_content: bool = True) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.key()}"}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _file_type(path: Path) -> str:
        suffix = path.suffix.lower().lstrip(".")
        if suffix == "jpeg":
            return "jpg"
        if suffix not in {"jpg", "png", "webp"}:
            raise EngineExecutionError(
                "REFERENCE_FORMAT_UNSUPPORTED",
                "Tripo aceita referências JPG, PNG ou WebP.",
                str(path),
            )
        return suffix

    @staticmethod
    def _unwrap(payload: dict[str, Any], action: str) -> dict[str, Any]:
        try:
            code = int(payload.get("code", 0))
        except (TypeError, ValueError):
            code = -1
        if code != 0:
            raise EngineExecutionError(
                "PROVIDER_REQUEST_FAILED",
                f"Tripo recusou {action}.",
                str(payload)[:3000],
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise EngineExecutionError(
                "PROVIDER_RESPONSE_INVALID",
                f"Tripo retornou resposta inválida em {action}.",
                str(payload)[:3000],
            )
        return data

    async def _upload(self, client: httpx.AsyncClient, path: Path) -> dict[str, str]:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise EngineExecutionError("REFERENCE_FILE_MISSING", "Arquivo para Tripo não encontrado", str(path))
        file_type = self._file_type(path)
        mime = mimetypes.guess_type(path.name)[0] or f"image/{file_type}"
        with path.open("rb") as stream:
            response = await client.post(
                f"{self.base_url}/upload/sts",
                headers=self.headers(json_content=False),
                files={"file": (path.name, stream, mime)},
            )
        payload = await self.ensure_success(response)
        data = self._unwrap(payload, "o upload")
        # Tripo's upload documentation calls this image_token while generation
        # endpoints call it file_token. Accept both names for compatibility.
        token = str(data.get("image_token") or data.get("file_token") or "").strip()
        if not token:
            raise EngineExecutionError("PROVIDER_RESPONSE_INVALID", "Tripo não retornou image_token/file_token", str(payload)[:3000])
        return {"type": file_type, "file_token": token}

    @classmethod
    def _ordered_references(cls, references: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        assigned: dict[str, dict[str, Any]] = {}
        unassigned: list[dict[str, Any]] = []
        for item in references:
            role = str(item.get("role") or "").lower()
            if role in cls._VIEW_ORDER and role not in assigned:
                assigned[role] = item
            else:
                unassigned.append(item)
        for item in unassigned:
            role = next((candidate for candidate in cls._VIEW_ORDER if candidate not in assigned), None)
            if role is None:
                break
            assigned[role] = item
        if assigned and "front" not in assigned:
            first_role = next(iter(assigned))
            assigned["front"] = assigned.pop(first_role)
        return assigned

    async def invoke_mesh(
        self,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path,
        parameters: dict[str, Any],
        *,
        cancel_check: CancelCheck = None,
    ) -> dict[str, Any]:
        model_version = str(parameters.get("model") or parameters.get("model_version") or "v3.1-20260211")
        payload: dict[str, Any] = {
            "model_version": model_version,
            "texture": bool(parameters.get("texture", True)),
            "pbr": bool(parameters.get("pbr", True)),
        }
        documented_keys = (
            "face_limit", "geometry_quality", "auto_size", "quad", "smart_low_poly",
            "export_uv", "model_seed", "texture_seed", "orientation",
            "texture_alignment", "texture_quality", "enable_image_autofix",
        )
        for key in documented_keys:
            if key in parameters and parameters[key] not in (None, ""):
                payload[key] = parameters[key]
        extra = parameters.get("payload")
        if isinstance(extra, dict):
            payload.update(extra)

        async with self.client(self.headers()) as client:
            if not references:
                if not prompt.strip():
                    raise EngineExecutionError("PROMPT_MISSING", "Text-to-3D do Tripo precisa de prompt")
                payload["type"] = "text_to_model"
                payload["prompt"] = prompt[:1024]
                if negative:
                    payload["negative_prompt"] = negative[:255]
            elif len(references) == 1:
                payload["type"] = "image_to_model"
                payload["file"] = await self._upload(client, Path(str(references[0]["path"])))
            else:
                ordered = self._ordered_references(references[:4])
                if len(ordered) < 2 or "front" not in ordered:
                    raise EngineExecutionError(
                        "MULTIVIEW_INPUT_INVALID",
                        "Tripo multiview exige ao menos duas imagens e uma vista frontal.",
                        f"papéis recebidos={sorted(ordered)}",
                    )
                payload["type"] = "multiview_to_model"
                files: list[dict[str, str]] = []
                for role in self._VIEW_ORDER:
                    item = ordered.get(role)
                    files.append(await self._upload(client, Path(str(item["path"]))) if item else {})
                payload["files"] = files

            created_payload = await self.ensure_success(await client.post(f"{self.base_url}/task", json=payload))
            created = self._unwrap(created_payload, "a criação da tarefa")
            task_id = str(created.get("task_id") or "").strip()
            if not task_id:
                raise EngineExecutionError("PROVIDER_TASK_ID_MISSING", "Tripo não retornou task_id", str(created_payload)[:3000])

            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            final_payload: dict[str, Any] | None = None
            final_data: dict[str, Any] | None = None
            while True:
                if cancel_check and cancel_check():
                    raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
                if asyncio.get_running_loop().time() >= deadline:
                    raise EngineExecutionError("PROVIDER_TIMEOUT", "A tarefa Tripo excedeu o tempo limite", task_id)
                status_payload = await self.ensure_success(await client.get(f"{self.base_url}/task/{task_id}"))
                data = self._unwrap(status_payload, "a consulta da tarefa")
                status = str(data.get("status") or "").lower()
                if status == "success":
                    final_payload, final_data = status_payload, data
                    break
                if status in {"failed", "banned", "expired", "cancelled", "canceled", "unknown"}:
                    raise EngineExecutionError(
                        "PROVIDER_TASK_FAILED",
                        f"Tripo terminou como {status}.",
                        str(data.get("error") or data.get("message") or status_payload)[:3000],
                    )
                await _sleep_or_cancel(self.poll_interval, cancel_check)

        assert final_payload is not None and final_data is not None
        output = final_data.get("output") or {}
        if not isinstance(output, dict):
            raise EngineExecutionError("PROVIDER_OUTPUT_MISSING", "Tripo concluiu sem objeto output", str(final_payload)[:3000])
        url = str(output.get("pbr_model") or output.get("model") or output.get("base_model") or "").strip()
        if not url:
            raise EngineExecutionError("PROVIDER_OUTPUT_MISSING", "Tripo concluiu sem URL de modelo", str(final_payload)[:3000])
        downloaded = await download_output(
            url,
            output_path,
            max_bytes=int(self.settings.get("max_output_bytes", 8 * 1024**3)),
            timeout_seconds=self.timeout_seconds,
            allow_private=self.allow_private,
        )
        return {
            **downloaded,
            "provider": self.provider_id,
            "task_id": task_id,
            "model_version": model_version,
            "task_type": payload.get("type"),
            "preview_url": output.get("rendered_image"),
            "output_url": url,
            "consumed_credit": final_data.get("consumed_credit"),
            "provider_payload": final_payload,
        }


class GenericRestProvider(HttpProvider):
    provider_id = "cloud.generic_rest"
    default_env = "GENERIC_PROVIDER_API_KEY"

    async def invoke(
        self,
        operation: str,
        prompt: str,
        negative: str,
        references: list[dict[str, Any]],
        output_path: Path,
        parameters: dict[str, Any],
        *,
        cancel_check: CancelCheck = None,
    ) -> dict[str, Any]:
        endpoint = str(parameters.get("endpoint") or self.settings.get("endpoint") or "").strip()
        if not endpoint:
            raise EngineExecutionError("PROVIDER_ENDPOINT_MISSING", "Generic REST precisa de endpoint explícito")
        env = str(self.settings.get("api_key_env") or self.default_env)
        key = os.getenv(env, "").strip()
        auth_type = str(self.settings.get("auth_type") or "bearer")
        headers = dict(self.settings.get("headers") or {})
        if key:
            if auth_type == "header":
                headers[str(self.settings.get("api_key_header") or "x-api-key")] = key
            elif auth_type == "bearer":
                headers["Authorization"] = f"Bearer {key}"
        headers.setdefault("Content-Type", "application/json")
        payload = dict(parameters.get("payload") or {})
        payload.setdefault(str(parameters.get("prompt_field") or "prompt"), prompt)
        if negative:
            payload.setdefault(str(parameters.get("negative_field") or "negative_prompt"), negative)
        encoded = [file_to_data_uri(Path(str(item["path"])), max_bytes=50 * 1024 * 1024) for item in references]
        if encoded:
            payload.setdefault(str(parameters.get("references_field") or "references"), encoded)
        method = str(parameters.get("method") or "POST").upper()
        async with self.client(headers) as client:
            response = await client.request(method, endpoint, json=payload)
            initial = await self.ensure_success(response)
            status_url = parameters.get("status_url") or initial.get(str(parameters.get("status_url_field") or "status_url"))
            if status_url:
                id_field = str(parameters.get("task_id_field") or "task_id")
                task_id = initial.get(id_field)
                if task_id:
                    status_url = str(status_url).replace("{task_id}", str(task_id))
                deadline = asyncio.get_running_loop().time() + self.timeout_seconds
                while True:
                    if cancel_check and cancel_check():
                        raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
                    if asyncio.get_running_loop().time() >= deadline:
                        raise EngineExecutionError("PROVIDER_TIMEOUT", "Provider REST excedeu o tempo limite")
                    current = await self.ensure_success(await client.get(str(status_url)))
                    status = str(current.get(str(parameters.get("status_field") or "status")) or "").upper()
                    if status in set(parameters.get("success_statuses") or ["COMPLETED", "SUCCEEDED", "SUCCESS", "DONE"]):
                        initial = current
                        break
                    if status in set(parameters.get("failure_statuses") or ["FAILED", "ERROR", "CANCELLED"]):
                        raise EngineExecutionError("PROVIDER_TASK_FAILED", f"Provider REST terminou como {status}", str(current)[:3000])
                    await _sleep_or_cancel(self.poll_interval, cancel_check)
        return await self.materialize(initial, output_path)
