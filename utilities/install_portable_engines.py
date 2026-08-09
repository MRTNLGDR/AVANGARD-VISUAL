#!/usr/bin/env python3
"""Install portable NCNN engines from their official GitHub releases.

Downloads are performed from official release assets only. The archive SHA-256,
release tag, URL, and installed binary path are written to install-report.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ENGINES = {
    "realesrgan": {
        "repo": "xinntao/Real-ESRGAN-ncnn-vulkan",
        "binary": "realesrgan-ncnn-vulkan",
        "target": "realesrgan-ncnn-vulkan",
    },
    "rife": {
        "repo": "nihui/rife-ncnn-vulkan",
        "binary": "rife-ncnn-vulkan",
        "target": "rife-ncnn-vulkan",
    },
}
USER_AGENT = "Avangard-Visual/0.3.0"


def request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def platform_tokens() -> tuple[list[str], list[str]]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        os_tokens = ["windows", "win64", "win"]
    elif system == "darwin":
        os_tokens = ["macos", "darwin", "mac"]
    elif system == "linux":
        os_tokens = ["ubuntu", "linux"]
    else:
        raise RuntimeError(f"Sistema não suportado: {system}")
    arch_tokens = ["x64", "amd64", "x86_64"] if machine in {"x86_64", "amd64"} else ["arm64", "aarch64"]
    return os_tokens, arch_tokens


def choose_asset(assets: list[dict]) -> dict:
    os_tokens, arch_tokens = platform_tokens()
    candidates = []
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if not name.endswith(".zip") or "source" in name:
            continue
        score = 0
        if any(token in name for token in os_tokens):
            score += 100
        if any(token in name for token in arch_tokens):
            score += 10
        candidates.append((score, int(asset.get("size", 0)), asset))
    candidates = [item for item in candidates if item[0] >= 100]
    if not candidates:
        names = [item.get("name") for item in assets]
        raise RuntimeError(f"Nenhum asset ZIP compatível encontrado. Assets: {names}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if existing and exc.code == 416:
            os.replace(partial, destination)
            return
        raise
    status = getattr(response, "status", 200)
    mode = "ab" if existing and status == 206 else "wb"
    if mode == "wb":
        existing = 0
    total = response.headers.get("Content-Length")
    total_bytes = existing + int(total) if total else None
    with response, partial.open(mode) as handle:
        downloaded = existing
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
            downloaded += len(chunk)
            if total_bytes:
                print(f"\r{downloaded / total_bytes * 100:6.2f}% ({downloaded/1024**2:.1f} MiB)", end="", flush=True)
    print()
    os.replace(partial, destination)


def install_engine(engine_id: str, root: Path, force: bool) -> dict:
    spec = ENGINES[engine_id]
    api_url = f"https://api.github.com/repos/{spec['repo']}/releases/latest"
    release = request_json(api_url)
    asset = choose_asset(release.get("assets", []))
    target = root / spec["target"]
    expected_binary = spec["binary"] + (".exe" if platform.system().lower() == "windows" else "")
    existing = list(target.rglob(expected_binary)) if target.exists() else []
    if existing and not force:
        return {
            "engine": engine_id,
            "status": "already-present",
            "binary": str(existing[0].resolve()),
            "release": release.get("tag_name"),
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"cinenode-{engine_id}-") as temp_name:
        temp = Path(temp_name)
        archive = temp / str(asset["name"])
        print(f"[{engine_id}] {release.get('tag_name')} -> {asset['name']}")
        download(str(asset["browser_download_url"]), archive)
        archive_hash = sha256(archive)
        extract = temp / "extract"
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                resolved = (extract / member.filename).resolve()
                try:
                    resolved.relative_to(extract.resolve())
                except ValueError as exc:
                    raise RuntimeError(f"Archive path traversal: {member.filename}") from exc
            zf.extractall(extract)
        binaries = list(extract.rglob(expected_binary))
        if not binaries:
            raise RuntimeError(f"Binário {expected_binary} ausente em {asset['name']}")
        package_root = binaries[0].parent
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(package_root, target)
        installed_binary = target / expected_binary
        if not installed_binary.is_file():
            nested = list(target.rglob(expected_binary))
            if not nested:
                raise RuntimeError(f"Instalação não contém {expected_binary}")
            installed_binary = nested[0]
        if platform.system().lower() != "windows":
            installed_binary.chmod(installed_binary.stat().st_mode | 0o111)
    return {
        "engine": engine_id,
        "status": "installed",
        "repo": spec["repo"],
        "release": release.get("tag_name"),
        "asset": asset.get("name"),
        "asset_url": asset.get("browser_download_url"),
        "asset_sha256": archive_hash,
        "binary": str(installed_binary.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engines", nargs="*", choices=list(ENGINES), default=list(ENGINES))
    parser.add_argument("--engines-dir", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    root = (args.engines_dir or Path(os.getenv("CINENODE_ENGINES_DIR", project_root / "data" / "engines"))).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = []
    for engine_id in args.engines or list(ENGINES):
        report.append(install_engine(engine_id, root, args.force))
    report_path = root / "install-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
