from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .common import EngineExecutionError, LogCallback, CancelCheck, find_executable, run_command


class WanGPEngine:
    engine_id = "wangp"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    def _root(self) -> Path | None:
        value = self.settings.get("root_path")
        return Path(value).expanduser().resolve() if value else None

    async def status(self) -> dict[str, Any]:
        root = self._root()
        if not root or not (root / "shared" / "api.py").is_file():
            return {"engine_id": self.engine_id, "available": False, "version": None, "detail": "Configure root_path para uma instalação WanGP que contenha shared/api.py"}
        python = find_executable(self.settings.get("python_path")) or sys.executable
        return {"engine_id": self.engine_id, "available": True, "version": "API", "detail": f"{root} via {python}"}

    async def generate(
        self,
        settings_payload: dict[str, Any],
        output_dir: Path,
        work_dir: Path,
        *,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> list[Path]:
        root = self._root()
        if not root or not (root / "shared" / "api.py").is_file():
            raise EngineExecutionError("WANGP_ROOT_MISSING", "Instalação WanGP inválida", str(root))
        python = find_executable(self.settings.get("python_path")) or sys.executable
        bridge = Path(__file__).with_name("wangp_bridge.py").resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        settings_file = work_dir / "wangp-settings.json"
        result_file = work_dir / "wangp-result.json"
        settings_file.write_text(json.dumps(settings_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        args = [
            python, str(bridge), "--root", str(root), "--settings", str(settings_file),
            "--result", str(result_file), "--output-dir", str(output_dir),
        ]
        if self.settings.get("config_path"):
            args.extend(["--config", str(self.settings["config_path"])])
        for item in self.settings.get("cli_args") or ["--attention", "sdpa", "--profile", "4"]:
            args.extend(["--cli-arg", str(item)])
        await run_command(
            args,
            timeout=int(self.settings.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not result_file.is_file():
            raise EngineExecutionError("WANGP_RESULT_MISSING", "A bridge WanGP não criou o resultado")
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        if not payload.get("success"):
            raise EngineExecutionError("WANGP_GENERATION_FAILED", "WanGP falhou", json.dumps(payload.get("errors"), ensure_ascii=False))
        outputs: list[Path] = []
        for item in payload.get("generated_files") or []:
            source = Path(item).resolve()
            if source.is_file():
                target = output_dir / source.name
                if source != target:
                    shutil.copy2(source, target)
                outputs.append(target)
        if not outputs:
            raise EngineExecutionError("WANGP_OUTPUT_MISSING", "WanGP não retornou arquivos gerados")
        return outputs
