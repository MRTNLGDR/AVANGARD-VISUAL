from __future__ import annotations

import base64
import ipaddress
import mimetypes
import socket
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from .engines.common import EngineExecutionError


_OUTPUT_CONTAINERS = {
    "output", "outputs", "generated", "images", "videos", "files", "artifacts",
    "data", "payload", "result",
}


_OUTPUT_KEYS = {
    "url", "uri", "image", "image_url", "video", "video_url", "audio", "audio_url",
    "file", "file_url", "model", "model_url", "mesh", "mesh_url", "glb", "glb_url",
    "download_url", "rendered_image_url",
}


def file_to_data_uri(path: Path, *, max_bytes: int = 50 * 1024 * 1024) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise EngineExecutionError("REFERENCE_FILE_MISSING", "Arquivo de referência não encontrado", str(path))
    size = path.stat().st_size
    if size > max_bytes:
        raise EngineExecutionError(
            "REFERENCE_TOO_LARGE",
            f"A referência excede o limite de {max_bytes} bytes.",
            f"{path} possui {size} bytes",
        )
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def decode_data_uri(value: str) -> tuple[bytes, str]:
    if not value.startswith("data:") or "," not in value:
        raise ValueError("Not a data URI")
    header, payload = value.split(",", 1)
    mime = header[5:].split(";", 1)[0] or "application/octet-stream"
    if ";base64" in header:
        try:
            return base64.b64decode(payload, validate=True), mime
        except ValueError as exc:
            raise EngineExecutionError("PROVIDER_OUTPUT_INVALID", "Provider returned invalid Base64 data") from exc
    return payload.encode("utf-8"), mime


def _is_private_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(normalized)
        return bool(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)
    except ValueError:
        pass
    try:
        for item in socket.getaddrinfo(normalized, None):
            address = ipaddress.ip_address(item[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                return True
    except OSError:
        return False
    return False


def validate_remote_url(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise EngineExecutionError("REMOTE_URL_INVALID", "URL remota inválida", url[:500])
    if parsed.username or parsed.password:
        raise EngineExecutionError("REMOTE_URL_INVALID", "Credenciais embutidas na URL não são permitidas")
    if not allow_private and _is_private_host(parsed.hostname):
        raise EngineExecutionError("REMOTE_URL_BLOCKED", "URL remota aponta para rede privada/loopback", parsed.hostname)
    return url


async def download_output(
    value: str,
    destination: Path,
    *,
    max_bytes: int = 8 * 1024**3,
    timeout_seconds: int = 1800,
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    part.unlink(missing_ok=True)
    try:
        if value.startswith("data:"):
            content, mime = decode_data_uri(value)
            if len(content) > max_bytes:
                raise EngineExecutionError("PROVIDER_OUTPUT_TOO_LARGE", "Saída Base64 excede o limite permitido")
            part.write_bytes(content)
            part.replace(destination)
            return {"path": str(destination), "size_bytes": len(content), "content_type": mime, "source": "data-uri"}

        validate_remote_url(value, allow_private=allow_private)
        total = 0
        content_type = "application/octet-stream"
        timeout = httpx.Timeout(timeout_seconds, connect=min(30.0, float(timeout_seconds)))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", value, headers=headers) as response:
                response.raise_for_status()
                final_url = str(response.url)
                validate_remote_url(final_url, allow_private=allow_private)
                content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
                with part.open("wb") as stream:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise EngineExecutionError("PROVIDER_OUTPUT_TOO_LARGE", f"Saída excede {max_bytes} bytes", final_url)
                        stream.write(chunk)
        if total == 0:
            raise EngineExecutionError("PROVIDER_OUTPUT_EMPTY", "Provider retornou arquivo vazio", value)
        part.replace(destination)
        return {"path": str(destination), "size_bytes": total, "content_type": content_type, "source": value}
    except httpx.HTTPStatusError as exc:
        raise EngineExecutionError(
            "PROVIDER_DOWNLOAD_FAILED",
            f"Falha HTTP {exc.response.status_code} ao baixar saída do provider",
            str(exc.response.url),
        ) from exc
    except httpx.HTTPError as exc:
        raise EngineExecutionError("PROVIDER_DOWNLOAD_FAILED", "Falha de rede ao baixar saída do provider", str(exc)) from exc
    finally:
        part.unlink(missing_ok=True)


def extract_urls(payload: Any) -> list[str]:
    """Extract media-like URLs/data URIs while preserving provider order and avoiding unrelated web links."""
    found: list[str] = []

    def add(value: str) -> None:
        if value.startswith(("http://", "https://", "data:")) and value not in found:
            found.append(value)

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, str):
            if key in _OUTPUT_KEYS or key in _OUTPUT_CONTAINERS or value.startswith("data:"):
                add(value)
            return
        if isinstance(value, list):
            for item in value:
                walk(item, key)
            return
        if isinstance(value, dict):
            # Common APIs put final files under these containers.
            for item_key, item_value in value.items():
                lowered = str(item_key).lower()
                if lowered in _OUTPUT_CONTAINERS:
                    walk(item_value, lowered)
                elif lowered in _OUTPUT_KEYS:
                    walk(item_value, lowered)

    walk(payload)
    return found


def first_output_url(payload: Any) -> str:
    urls = extract_urls(payload)
    if not urls:
        raise EngineExecutionError(
            "PROVIDER_OUTPUT_MISSING",
            "O provider concluiu a tarefa, mas não retornou uma URL/arquivo reconhecido.",
            str(payload)[:3000],
        )
    return urls[0]


def reference_payload(items: Iterable[dict[str, Any]], *, as_data_uri: bool = True, max_bytes: int = 20 * 1024 * 1024) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        value = file_to_data_uri(path, max_bytes=max_bytes) if as_data_uri else str(path)
        result.append({
            "value": value,
            "path": str(path),
            "role": str(item.get("role") or "reference"),
            "weight": float(item.get("weight", 1.0)),
            "note": str(item.get("note") or ""),
        })
    return result
