from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .common import (
    CancelCheck,
    EngineExecutionError,
    LogCallback,
    find_executable,
    require_executable,
    require_file,
    run_command,
)


MESH_SUFFIXES = {".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usdz"}


class LocalMeshEngines:
    """Adapters for local image/text-to-3D runtimes.

    The adapter never fabricates geometry. A node succeeds only when the selected
    upstream executable writes a real mesh file that can be verified on disk.
    """

    def __init__(
        self,
        trellis_cpp: dict[str, Any],
        triposr: dict[str, Any],
        generic_3d_cli: dict[str, Any],
        blender: dict[str, Any],
    ):
        self.trellis_cpp = dict(trellis_cpp or {})
        self.triposr = dict(triposr or {})
        self.generic_3d_cli = dict(generic_3d_cli or {})
        self.blender = dict(blender or {})

    async def status(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for engine_id, settings, key in (
            ("trellis_cpp", self.trellis_cpp, "binary_path"),
            ("blender", self.blender, "binary_path"),
        ):
            executable = find_executable(str(settings.get(key) or ""))
            results.append(
                {
                    "engine_id": engine_id,
                    "available": bool(executable),
                    "version": "installed" if executable else None,
                    "detail": executable or f"{settings.get(key)!r} não encontrado",
                }
            )

        tripo_python = find_executable(str(self.triposr.get("python_path") or sys.executable))
        tripo_script = self._resolve_script(self.triposr, "run.py")
        results.append(
            {
                "engine_id": "triposr",
                "available": bool(tripo_python and tripo_script),
                "version": "installed" if tripo_python and tripo_script else None,
                "detail": f"python={tripo_python or 'missing'}; script={tripo_script or 'missing'}",
            }
        )

        generic_command = self.generic_3d_cli.get("command")
        generic_executable = None
        if isinstance(generic_command, list) and generic_command:
            generic_executable = find_executable(str(generic_command[0]))
        results.append(
            {
                "engine_id": "generic_3d_cli",
                "available": bool(generic_executable),
                "version": "configured" if generic_executable else None,
                "detail": generic_executable or "command[] explícito não configurado",
            }
        )
        return results

    @staticmethod
    def _resolve_script(settings: dict[str, Any], default_relative: str, *, explicit_key: str = "script_path") -> Path | None:
        explicit = str(settings.get(explicit_key) or "").strip()
        if explicit:
            path = Path(os.path.expandvars(os.path.expanduser(explicit))).resolve()
            return path if path.is_file() else None
        root = str(settings.get("root_path") or "").strip()
        if not root:
            return None
        path = (Path(os.path.expandvars(os.path.expanduser(root))).resolve() / default_relative).resolve()
        return path if path.is_file() else None

    @staticmethod
    def _require_references(references: list[dict[str, Any]], engine_id: str) -> list[Path]:
        if not references:
            raise EngineExecutionError(
                "REFERENCE_INPUT_MISSING",
                f"{engine_id} local precisa de pelo menos uma imagem de referência.",
            )
        paths: list[Path] = []
        for item in references:
            paths.append(require_file(str(item.get("path") or ""), f"reference:{item.get('role', 'reference')}"))
        return paths

    @staticmethod
    def _newest_mesh(directory: Path) -> Path | None:
        candidates = [path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in MESH_SUFFIXES]
        return max(candidates, key=lambda item: item.stat().st_mtime_ns) if candidates else None

    async def generate(
        self,
        engine_id: str,
        prompt: str,
        references: list[dict[str, Any]],
        output_path: Path,
        config: dict[str, Any],
        *,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = engine_id.removeprefix("local.")
        if normalized == "trellis_cpp":
            return await self._trellis_cpp(references, output_path, config, cancel_check=cancel_check, log=log)
        if normalized == "triposr":
            return await self._triposr(references, output_path, config, cancel_check=cancel_check, log=log)
        if normalized == "generic_3d_cli":
            return await self._generic_cli(prompt, references, output_path, config, cancel_check=cancel_check, log=log)
        raise EngineExecutionError("ENGINE_NOT_SUPPORTED", f"Engine 3D local não suportada: {engine_id}")

    async def _trellis_cpp(
        self,
        references: list[dict[str, Any]],
        output_path: Path,
        config: dict[str, Any],
        *,
        cancel_check: CancelCheck | None,
        log: LogCallback | None,
    ) -> dict[str, Any]:
        executable = require_executable(self.trellis_cpp.get("binary_path"), "trellis.cpp")
        images = self._require_references(references, "trellis.cpp")
        if output_path.suffix.lower() not in {".glb", ".gltf"}:
            output_path = output_path.with_suffix(".glb")
        args = [executable, str(images[0]), str(output_path)]
        models_path = str(config.get("models_path") or self.trellis_cpp.get("models_path") or "").strip()
        if models_path:
            args.extend(["--models", str(Path(models_path).expanduser().resolve())])
        option_map = {
            "resolution": "--res",
            "seed": "--seed",
            "faces": "--faces",
            "atlas_size": "--atlas",
            "steps": "--steps",
        }
        for key, flag in option_map.items():
            value = config.get(key)
            if value not in (None, "", -1):
                args.extend([flag, str(value)])
        for raw in config.get("extra_args") or self.trellis_cpp.get("extra_args") or []:
            args.append(str(raw))
        result = await run_command(
            args,
            cwd=Path(str(self.trellis_cpp.get("root_path"))).expanduser().resolve() if self.trellis_cpp.get("root_path") else None,
            timeout=int(config.get("timeout_seconds") or self.trellis_cpp.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "trellis.cpp não criou um GLB válido", str(output_path))
        return {"path": str(output_path.resolve()), "engine": "local.trellis_cpp", "command": result.args}

    async def _triposr(
        self,
        references: list[dict[str, Any]],
        output_path: Path,
        config: dict[str, Any],
        *,
        cancel_check: CancelCheck | None,
        log: LogCallback | None,
    ) -> dict[str, Any]:
        python = require_executable(self.triposr.get("python_path") or sys.executable, "Python/TripoSR")
        script = self._resolve_script(self.triposr, "run.py")
        if not script:
            raise EngineExecutionError("ENGINE_SCRIPT_MISSING", "run.py do TripoSR não foi encontrado", str(self.triposr.get("root_path") or ""))
        images = self._require_references(references, "TripoSR")
        work_dir = output_path.parent / f".{output_path.stem}-triposr"
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True)
        args = [python, str(script), *[str(path) for path in images], "--output-dir", str(work_dir)]
        if bool(config.get("bake_texture", True)):
            args.append("--bake-texture")
        args.extend(["--texture-resolution", str(int(config.get("texture_resolution", 2048)))])
        if config.get("mc_resolution"):
            args.extend(["--mc-resolution", str(int(config["mc_resolution"]))])
        if config.get("chunk_size"):
            args.extend(["--chunk-size", str(int(config["chunk_size"]))])
        if bool(config.get("no_remove_bg", False)):
            args.append("--no-remove-bg")
        for raw in config.get("extra_args") or self.triposr.get("extra_args") or []:
            args.append(str(raw))
        result = await run_command(
            args,
            cwd=script.parent,
            timeout=int(config.get("timeout_seconds") or self.triposr.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        produced = self._newest_mesh(work_dir)
        if not produced:
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "TripoSR não criou OBJ/GLB/PLY", str(work_dir))
        final = output_path.with_suffix(produced.suffix.lower())
        shutil.copy2(produced, final)
        return {
            "path": str(final.resolve()),
            "engine": "local.triposr",
            "command": result.args,
            "native_output": str(produced.resolve()),
            "note": "TripoSR normalmente produz OBJ; use mesh.export com Blender para GLB.",
        }

    async def _generic_cli(
        self,
        prompt: str,
        references: list[dict[str, Any]],
        output_path: Path,
        config: dict[str, Any],
        *,
        cancel_check: CancelCheck | None,
        log: LogCallback | None,
    ) -> dict[str, Any]:
        command = config.get("command") or self.generic_3d_cli.get("command")
        if not isinstance(command, list) or not command:
            raise EngineExecutionError("ENGINE_COMMAND_MISSING", "generic_3d_cli exige command como lista de argumentos")
        image_paths = self._require_references(references, "generic_3d_cli") if references else []
        substitutions = {
            "{{prompt}}": prompt,
            "{{output}}": str(output_path),
            "{{input}}": str(image_paths[0]) if image_paths else "",
            "{{references_json}}": json.dumps([str(path) for path in image_paths]),
        }
        args: list[str] = []
        for item in command:
            value = str(item)
            for token, replacement in substitutions.items():
                value = value.replace(token, replacement)
            args.append(value)
        args[0] = require_executable(args[0], "generic_3d_cli")
        result = await run_command(
            args,
            cwd=Path(str(config["cwd"])).expanduser().resolve() if config.get("cwd") else None,
            timeout=int(config.get("timeout_seconds") or self.generic_3d_cli.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "CLI 3D não criou a saída declarada", str(output_path))
        return {"path": str(output_path.resolve()), "engine": "local.generic_3d_cli", "command": result.args}

    async def convert(
        self,
        input_path: Path,
        output_path: Path,
        *,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        blender = require_executable(self.blender.get("binary_path") or "blender", "Blender")
        input_path = require_file(str(input_path), "input_mesh")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        script = (
            "import bpy,sys,pathlib; "
            "a=sys.argv[sys.argv.index('--')+1:]; src,dst=a[0],a[1]; "
            "bpy.ops.wm.read_factory_settings(use_empty=True); ext=pathlib.Path(src).suffix.lower(); "
            "({'obj':bpy.ops.wm.obj_import,'fbx':bpy.ops.import_scene.fbx,'ply':bpy.ops.wm.ply_import,'stl':bpy.ops.wm.stl_import,'gltf':bpy.ops.import_scene.gltf,'glb':bpy.ops.import_scene.gltf}[ext[1:]])(filepath=src); "
            "out=pathlib.Path(dst).suffix.lower(); "
            "(bpy.ops.export_scene.gltf(filepath=dst,export_format='GLB') if out=='.glb' else bpy.ops.export_scene.gltf(filepath=dst,export_format='GLTF_SEPARATE'))"
        )
        result = await run_command(
            [blender, "--background", "--python-expr", script, "--", str(input_path), str(output_path)],
            timeout=int(self.blender.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Blender não criou o mesh exportado", str(output_path))
        return {"path": str(output_path.resolve()), "engine": "blender", "command": result.args}

    async def turntable(
        self,
        input_path: Path,
        output_path: Path,
        config: dict[str, Any],
        *,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        blender = require_executable(self.blender.get("binary_path") or "blender", "Blender")
        input_path = require_file(str(input_path), "input_mesh")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        helper = Path(__file__).with_name("blender_turntable.py")
        if not helper.is_file():
            raise EngineExecutionError("ENGINE_SCRIPT_MISSING", "Script de turntable Blender ausente", str(helper))
        result = await run_command(
            [
                blender,
                "--background",
                "--python",
                str(helper),
                "--",
                str(input_path),
                str(output_path),
                str(int(config.get("width", 1024))),
                str(int(config.get("height", 1024))),
                str(int(config.get("frames", 120))),
                str(int(config.get("fps", 30))),
            ],
            timeout=int(config.get("timeout_seconds") or self.blender.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Blender não criou o turntable", str(output_path))
        return {"path": str(output_path.resolve()), "engine": "blender", "command": result.args}
