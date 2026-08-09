#!/usr/bin/env python3
"""Static supply-chain gate for cloned upstream repositories.

The gate is intentionally dependency-free and runs before package-manager install
scripts. It rejects hidden Unicode control payloads in tracked text files and
records lifecycle utilities/binaries for human review. It does not claim to replace
malware scanning, signature verification, or a sandbox.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

# Characters used by hidden-source attacks or bidirectional source spoofing.
# FEFF is accepted only as the first character of a UTF-8 text file (BOM).
INVISIBLE_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x180B, 0x180D, "MONGOLIAN_FREE_VARIATION_SELECTOR"),
    (0x200B, 0x200F, "ZERO_WIDTH_OR_DIRECTIONAL_MARK"),
    (0x202A, 0x202E, "BIDI_EMBEDDING_OR_OVERRIDE"),
    (0x2060, 0x206F, "WORD_JOINER_OR_BIDI_ISOLATE"),
    (0xFE00, 0xFE0F, "VARIATION_SELECTOR"),
    (0xFEFF, 0xFEFF, "ZERO_WIDTH_NO_BREAK_SPACE"),
    (0xFFF9, 0xFFFB, "INTERLINEAR_ANNOTATION"),
    (0xE0000, 0xE007F, "TAG_CHARACTER"),
    (0xE0100, 0xE01EF, "VARIATION_SELECTOR_SUPPLEMENT"),
)
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".m", ".mm", ".rs",
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".xml", ".html",
    ".css", ".scss", ".sass", ".less", ".md", ".mdx", ".txt", ".sh",
    ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".gradle",
    ".properties", ".ini", ".cfg", ".conf", ".env", ".sql", ".go",
    ".java", ".kt", ".kts", ".swift", ".rb", ".php", ".vue", ".svelte",
}
TEXT_NAMES = {
    "Dockerfile", "Makefile", "CMakeLists.txt", "LICENSE", "LICENSE.txt",
    "COPYING", "NOTICE", ".gitignore", ".gitattributes", ".gitmodules",
    "package.json", "bun.lock", "pnpm-lock.yaml", "package-lock.json",
}
BINARY_SUFFIXES = {
    ".exe", ".dll", ".dylib", ".so", ".bin", ".wasm", ".node", ".jar",
    ".apk", ".appimage", ".deb", ".rpm", ".msi", ".pkg", ".dmg",
}
LIFECYCLE_KEYS = {"preinstall", "install", "postinstall", "prepare", "prepublish", "prepublishOnly"}


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    path: str
    detail: str
    line: int | None = None
    column: int | None = None
    codepoint: str | None = None


def _tracked_paths(root: Path) -> list[Path]:
    if (root / ".git").exists():
        raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
        return [root / item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]
    ignored = {".git", ".runtime", ".pytest_cache", "__pycache__", "node_modules", "data"}
    return [
        path for path in root.rglob("*")
        if path.is_file() and not ignored.intersection(path.relative_to(root).parts)
    ]


def _is_probably_text(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env")


def _invisible_kind(codepoint: int) -> str | None:
    for start, end, name in INVISIBLE_RANGES:
        if start <= codepoint <= end:
            return name
    return None


def scan_repository(root: Path) -> dict:
    root = root.resolve()
    findings: list[Finding] = []
    scanned_files = 0
    text_files = 0
    binary_files = 0

    for path in _tracked_paths(root):
        if not path.is_file():
            continue
        scanned_files += 1
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() in BINARY_SUFFIXES:
            binary_files += 1
            findings.append(Finding("WARN", "TRACKED_BINARY", rel, "Arquivo executável/binário rastreado; revisar origem e assinatura."))
            continue
        if not _is_probably_text(path):
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(Finding("HIGH", "READ_ERROR", rel, str(exc)))
            continue
        if b"\x00" in data[:8192]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("WARN", "NON_UTF8_TEXT", rel, "Arquivo textual não é UTF-8; revisar manualmente."))
            continue
        text_files += 1
        line = 1
        column = 0
        for index, char in enumerate(text):
            if char == "\n":
                line += 1
                column = 0
                continue
            column += 1
            codepoint = ord(char)
            kind = _invisible_kind(codepoint)
            if not kind:
                continue
            # UTF-8 BOM is allowed only at the very beginning.
            if codepoint == 0xFEFF and index == 0:
                continue
            # U+FE0F is the normal emoji presentation selector. Record it for
            # review, but do not reject a repository solely for legitimate emoji.
            severity = "WARN" if codepoint == 0xFE0F else "CRITICAL"
            findings.append(
                Finding(
                    severity,
                    "INVISIBLE_UNICODE",
                    rel,
                    kind,
                    line=line,
                    column=column,
                    codepoint=f"U+{codepoint:04X}",
                )
            )

        if path.name == "package.json":
            try:
                package = json.loads(text.lstrip("\ufeff"))
            except json.JSONDecodeError as exc:
                findings.append(Finding("HIGH", "INVALID_PACKAGE_JSON", rel, str(exc), line=exc.lineno, column=exc.colno))
            else:
                scripts = package.get("scripts") if isinstance(package, dict) else None
                if isinstance(scripts, dict):
                    for key in sorted(LIFECYCLE_KEYS.intersection(scripts)):
                        findings.append(
                            Finding(
                                "INFO",
                                "PACKAGE_LIFECYCLE_SCRIPT",
                                rel,
                                f"{key}: {scripts[key]}",
                            )
                        )

    critical = [item for item in findings if item.severity == "CRITICAL"]
    high = [item for item in findings if item.severity == "HIGH"]
    status = "REJECTED" if critical else ("REVIEW" if high else "ACCEPTABLE")
    return {
        "schema_version": 1,
        "root": str(root),
        "status": status,
        "scanned_files": scanned_files,
        "text_files": text_files,
        "binary_files": binary_files,
        "summary": {
            "critical": len(critical),
            "high": len(high),
            "warn": sum(1 for item in findings if item.severity == "WARN"),
            "info": sum(1 for item in findings if item.severity == "INFO"),
        },
        "findings": [asdict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita um clone upstream antes de qualquer instalação")
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fail-on", choices=["critical", "high"], default="critical")
    args = parser.parse_args()
    report = scan_repository(args.root)
    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if report["summary"]["critical"]:
        return 20
    if args.fail_on == "high" and report["summary"]["high"]:
        return 21
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
