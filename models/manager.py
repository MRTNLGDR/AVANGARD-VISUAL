#!/usr/bin/env python3
"""Resumable, checksum-verifying local model installer for Avangard Visual.

This setup utility downloads user-selected local weights into CINENODE_MODELS_DIR.
The application can also call explicitly enabled cloud providers, but this installer
never sends prompts or media to inference APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class ModelFile:
    repo_id: str
    filename: str
    destination: str
    sha256: str | None
    gated: bool = False


BUNDLES: dict[str, dict] = {
    "z-image-turbo-fast": {
        "title": "Z-Image Turbo Q3_K + Qwen3 4B Q4_K_M",
        "kind": "image",
        "recommended": True,
        "approx_download_gb": 6.0,
        "files": [
            ModelFile(
                "leejet/Z-Image-Turbo-GGUF",
                "z_image_turbo-Q3_K.gguf",
                "z-image-turbo/z_image_turbo-Q3_K.gguf",
                "4b44bdaa7814f20d7cf144e3939bd93aa32f50660204dd0c2aea5c5376232980",
            ),
            ModelFile(
                "black-forest-labs/FLUX.1-schnell",
                "ae.safetensors",
                "z-image-turbo/ae.safetensors",
                "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
                gated=True,
            ),
            ModelFile(
                "unsloth/Qwen3-4B-Instruct-2507-GGUF",
                "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
                "z-image-turbo/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
                "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
            ),
        ],
    },
    "wan21-t2v-1.3b-fast": {
        "title": "Wan 2.1 T2V 1.3B FP16 + UMT5 Q5_K_M",
        "kind": "video",
        "recommended": True,
        "approx_download_gb": 7.3,
        "files": [
            ModelFile(
                "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors",
                "wan21/wan2.1_t2v_1.3B_fp16.safetensors",
                "be531024cd9018cb5b48c40cfbb6a6191645b1c792eb8bf4f8c1c6e10f924dc5",
            ),
            ModelFile(
                "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "split_files/vae/wan_2.1_vae.safetensors",
                "wan21/wan_2.1_vae.safetensors",
                "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
            ),
            ModelFile(
                "city96/umt5-xxl-encoder-gguf",
                "umt5-xxl-encoder-Q5_K_M.gguf",
                "wan21/umt5-xxl-encoder-Q5_K_M.gguf",
                "eaea358bb438c5d211721a4feecc162000e3636e9cb96f51e216f1f44ebd12ce",
            ),
        ],
    },
    "wan21-i2v-14b-first-frame": {
        "title": "Wan 2.1 I2V 14B Q4_K_M — primeiro frame",
        "kind": "video",
        "recommended": False,
        "approx_download_gb": 17.5,
        "files": [
            ModelFile(
                "city96/Wan2.1-I2V-14B-720P-gguf",
                "wan2.1-i2v-14b-720p-Q4_K_M.gguf",
                "wan21/wan2.1-i2v-14b-720p-Q4_K_M.gguf",
                "ffecd91e4b636d8e3e43f3fa388218158ba447109547bde777c6d67ef4fe42a4",
            ),
            ModelFile(
                "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "split_files/vae/wan_2.1_vae.safetensors",
                "wan21/wan_2.1_vae.safetensors",
                "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
            ),
            ModelFile(
                "city96/umt5-xxl-encoder-gguf",
                "umt5-xxl-encoder-Q5_K_M.gguf",
                "wan21/umt5-xxl-encoder-Q5_K_M.gguf",
                "eaea358bb438c5d211721a4feecc162000e3636e9cb96f51e216f1f44ebd12ce",
            ),
            ModelFile(
                "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "split_files/clip_vision/clip_vision_h.safetensors",
                "wan21/clip_vision_h.safetensors",
                "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
            ),
        ],
    },
    "wan21-flf2v-14b-720p-q4": {
        "title": "Wan 2.1 FLF2V 14B Q4_K_M — start + end frame",
        "kind": "video",
        "recommended": False,
        "approx_download_gb": 17.5,
        "files": [
            ModelFile(
                "city96/Wan2.1-FLF2V-14B-720P-gguf",
                "wan2.1-flf2v-14b-720p-Q4_K_M.gguf",
                "wan21/wan2.1-flf2v-14b-720p-Q4_K_M.gguf",
                "7652d7d8b0795009ff21ed83d806af762aae8a8faa8640dd07b3a67e4dfab445",
            ),
            ModelFile(
                "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "split_files/vae/wan_2.1_vae.safetensors",
                "wan21/wan_2.1_vae.safetensors",
                "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
            ),
            ModelFile(
                "city96/umt5-xxl-encoder-gguf",
                "umt5-xxl-encoder-Q5_K_M.gguf",
                "wan21/umt5-xxl-encoder-Q5_K_M.gguf",
                "eaea358bb438c5d211721a4feecc162000e3636e9cb96f51e216f1f44ebd12ce",
            ),
            ModelFile(
                "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "split_files/clip_vision/clip_vision_h.safetensors",
                "wan21/clip_vision_h.safetensors",
                "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
            ),
        ],
    },
}


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def models_root(root: Path | None) -> Path:
    if root:
        return root.expanduser().resolve()
    env = os.getenv("CINENODE_MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    project_root = Path(__file__).resolve().parents[1]
    return (project_root / "data" / "models").resolve()


def list_bundles(as_json: bool) -> int:
    payload = {
        key: {**{k: v for k, v in value.items() if k != "files"}, "files": [asdict(item) for item in value["files"]]}
        for key, value in BUNDLES.items()
    }
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for key, value in payload.items():
            print(f"{key}: {value['title']} (~{value['approx_download_gb']} GB)")
            for item in value["files"]:
                marker = " [aceite/token HF]" if item["gated"] else ""
                print(f"  - {item['repo_id']}::{item['filename']} -> {item['destination']}{marker}")
    return 0


def require_huggingface_hub():
    try:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import HfHubHTTPError, GatedRepoError
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub não está instalado. Execute o wrapper download-models ou: "
            "python -m pip install 'huggingface-hub>=0.27,<2'"
        ) from exc
    return hf_hub_download, HfHubHTTPError, GatedRepoError


def install_file(item: ModelFile, root: Path, *, force: bool, token: str | None) -> dict:
    destination = (root / item.destination).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Destino inválido fora da pasta de modelos: {destination}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.is_file() and not force:
        actual = sha256_file(destination)
        if item.sha256 and actual != item.sha256:
            raise RuntimeError(
                f"Checksum inválido em {destination}. Esperado {item.sha256}, obtido {actual}. "
                "Use --force somente após verificar a origem."
            )
        return {"destination": str(destination), "sha256": actual, "status": "already-present"}

    hf_hub_download, HfHubHTTPError, GatedRepoError = require_huggingface_hub()
    cache = root / ".hf-cache"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        cached = Path(
            hf_hub_download(
                repo_id=item.repo_id,
                filename=item.filename,
                cache_dir=cache,
                token=token,
                resume_download=True,
            )
        ).resolve()
    except GatedRepoError as exc:
        raise RuntimeError(
            f"O modelo {item.repo_id} exige aceite da licença no Hugging Face e HF_TOKEN. "
            f"Aceite os termos na página oficial, defina HF_TOKEN e tente novamente. Detalhe: {exc}"
        ) from exc
    except HfHubHTTPError as exc:
        raise RuntimeError(f"Falha ao baixar {item.repo_id}::{item.filename}: {exc}") from exc

    actual = sha256_file(cached)
    if item.sha256 and actual != item.sha256:
        raise RuntimeError(
            f"Checksum remoto inválido para {item.repo_id}::{item.filename}. "
            f"Esperado {item.sha256}, obtido {actual}. Arquivo não foi instalado."
        )

    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        os.link(cached, temporary)
    except OSError:
        shutil.copy2(cached, temporary)
    os.replace(temporary, destination)
    return {"destination": str(destination), "sha256": actual, "status": "installed"}


def install_bundle(bundle_id: str, root: Path, *, force: bool, token: str | None) -> int:
    if bundle_id == "recommended":
        selected = [key for key, value in BUNDLES.items() if value.get("recommended")]
    elif bundle_id == "all":
        selected = list(BUNDLES)
    else:
        if bundle_id not in BUNDLES:
            raise SystemExit(f"Bundle desconhecido: {bundle_id}. Use 'list'.")
        selected = [bundle_id]

    root.mkdir(parents=True, exist_ok=True)
    report = {"models_root": str(root), "bundles": {}, "success": True}
    for key in selected:
        report["bundles"][key] = []
        print(f"\n[{key}] {BUNDLES[key]['title']}", flush=True)
        for item in BUNDLES[key]["files"]:
            print(f"Baixando/verificando {item.repo_id}::{item.filename}", flush=True)
            result = install_file(item, root, force=force, token=token)
            report["bundles"][key].append(result)
            print(f"  {result['status']}: {result['destination']}", flush=True)

    report_path = root / "model-install-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRelatório: {report_path}")
    return 0


def verify(root: Path, bundle_id: str) -> int:
    selected = list(BUNDLES) if bundle_id == "all" else [bundle_id]
    failures = []
    report = []
    for key in selected:
        if key not in BUNDLES:
            raise SystemExit(f"Bundle desconhecido: {key}")
        for item in BUNDLES[key]["files"]:
            path = root / item.destination
            if not path.is_file():
                report.append({"bundle": key, "path": str(path), "status": "missing"})
                failures.append(str(path))
                continue
            actual = sha256_file(path)
            status = "ok" if not item.sha256 or actual == item.sha256 else "checksum-mismatch"
            report.append({"bundle": key, "path": str(path), "status": status, "sha256": actual})
            if status != "ok":
                failures.append(str(path))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Gerenciador de modelos locais do Avangard Visual")
    parser.add_argument("--models-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    install_parser = sub.add_parser("install")
    install_parser.add_argument("bundle", choices=[*BUNDLES, "recommended", "all"])
    install_parser.add_argument("--force", action="store_true")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("bundle", choices=[*BUNDLES, "all"])
    args = parser.parse_args()
    root = models_root(args.models_dir)
    if args.command == "list":
        return list_bundles(args.json)
    if args.command == "install":
        return install_bundle(args.bundle, root, force=args.force, token=os.getenv("HF_TOKEN"))
    if args.command == "verify":
        return verify(root, args.bundle)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
