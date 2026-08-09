from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    EngineExecutionError,
    LogCallback,
    CancelCheck,
    find_executable,
    require_executable,
    require_file,
    run_command,
)


class StableDiffusionCppEngine:
    engine_id = "sd_cpp"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    async def status(self) -> dict[str, Any]:
        executable = find_executable(self.settings.get("binary_path"))
        if not executable:
            return {"engine_id": self.engine_id, "available": False, "detail": "sd-cli não encontrado", "version": None}
        try:
            result = await run_command([executable, "--version"], timeout=20)
            version = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else "installed"
            return {"engine_id": self.engine_id, "available": True, "detail": executable, "version": version[:300]}
        except Exception as exc:
            # Older builds may not expose --version; existence still proves installability.
            return {"engine_id": self.engine_id, "available": True, "detail": f"{executable} ({exc})", "version": "unknown"}

    @staticmethod
    def _append_model_args(args: list[str], profile: dict[str, Any]) -> None:
        if profile.get("model"):
            args.extend(["-m", str(require_file(profile["model"], "model"))])
        elif profile.get("diffusion_model"):
            args.extend(["--diffusion-model", str(require_file(profile["diffusion_model"], "diffusion_model"))])
        else:
            raise EngineExecutionError("MODEL_PATH_MISSING", "O perfil não define model nem diffusion_model")
        option_map = {
            "high_noise_diffusion_model": "--high-noise-diffusion-model",
            "vae": "--vae",
            "tae": "--tae",
            "llm": "--llm",
            "clip_l": "--clip_l",
            "clip_g": "--clip_g",
            "t5xxl": "--t5xxl",
            "clip_vision": "--clip_vision",
        }
        for key, flag in option_map.items():
            value = profile.get(key)
            if value:
                args.extend([flag, str(require_file(value, key))])

    async def generate_image(
        self,
        profile: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        options: dict[str, Any],
        *,
        input_image: Path | None = None,
        mask_image: Path | None = None,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.settings.get("binary_path"), self.engine_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        defaults = dict(profile.get("defaults") or {})
        merged = {**defaults, **{key: value for key, value in options.items() if value is not None}}
        args = [executable]
        self._append_model_args(args, profile)
        args.extend([
            "-p", prompt,
            "-n", negative_prompt or "",
            "-W", str(int(merged.get("width", 1024))),
            "-H", str(int(merged.get("height", 1024))),
            "--steps", str(int(merged.get("steps", 8))),
            "--cfg-scale", str(float(merged.get("cfg_scale", 1.0))),
            "--sampling-method", str(merged.get("sampling_method", "euler")),
            "-s", str(int(merged.get("seed", -1))),
            "-o", str(output_path),
            "--diffusion-fa",
        ])
        if input_image:
            args.extend(["-i", str(require_file(str(input_image), "input_image"))])
            args.extend(["--strength", str(float(merged.get("strength", 0.65)))])
        if mask_image:
            # The CLI flag is version-sensitive. Do not guess silently: callers must
            # explicitly supply mask_flag after verifying the installed sd-cli build.
            mask_flag = str(merged.get("mask_flag") or "").strip()
            if not mask_flag:
                raise EngineExecutionError(
                    "ENGINE_MASK_FLAG_REQUIRED",
                    "Inpainting local exige mask_flag compatível com a versão instalada do sd-cli.",
                    "Configure mask_flag no nó/perfil ou use ComfyUI/cloud; o mask não será ignorado.",
                )
            args.extend([mask_flag, str(require_file(str(mask_image), "mask_image"))])
        if bool(merged.get("offload_to_cpu", True)):
            args.append("--offload-to-cpu")
        if merged.get("extra_args"):
            args.extend(str(value) for value in merged["extra_args"])
        result = await run_command(
            args,
            timeout=int(self.settings.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not output_path.is_file():
            raise EngineExecutionError(
                "ENGINE_OUTPUT_MISSING",
                "sd.cpp terminou sem criar a imagem solicitada.",
                str(output_path),
            )
        return {"path": str(output_path), "command": result.args, "stdout_tail": result.stdout.splitlines()[-20:]}

    async def generate_video(
        self,
        profile: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        options: dict[str, Any],
        *,
        input_image: Path | None = None,
        end_image: Path | None = None,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.settings.get("binary_path"), self.engine_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        defaults = dict(profile.get("defaults") or {})
        merged = {**defaults, **{key: value for key, value in options.items() if value is not None}}
        # stable-diffusion.cpp currently writes video containers as AVI/WebM, not MP4.
        # Generate a deterministic native AVI and transcode only after inference succeeds.
        native_output = output_path if output_path.suffix.lower() == ".avi" else output_path.with_suffix(".native.avi")
        native_output.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        args = [executable, "-M", "vid_gen"]
        self._append_model_args(args, profile)
        args.extend([
            "-p", prompt,
            "-n", negative_prompt or "",
            "-W", str(int(merged.get("width", 832))),
            "-H", str(int(merged.get("height", 480))),
            "--steps", str(int(merged.get("steps", 20))),
            "--cfg-scale", str(float(merged.get("cfg_scale", 6.0))),
            "--sampling-method", str(merged.get("sampling_method", "euler")),
            "--video-frames", str(int(merged.get("frames", 33))),
            "--fps", str(int(merged.get("fps", 16))),
            "--flow-shift", str(float(merged.get("flow_shift", 3.0))),
            "-s", str(int(merged.get("seed", -1))),
            "-o", str(native_output),
            "--diffusion-fa",
        ])
        if profile.get("high_noise_diffusion_model"):
            args.extend([
                "--high-noise-steps", str(int(merged.get("high_noise_steps", 8))),
                "--high-noise-cfg-scale", str(float(merged.get("high_noise_cfg_scale", merged.get("cfg_scale", 3.5)))),
                "--high-noise-sampling-method", str(merged.get("high_noise_sampling_method", "euler")),
            ])
        if input_image:
            args.extend(["-i", str(require_file(str(input_image), "input_image"))])
        if end_image:
            if not input_image:
                raise EngineExecutionError(
                    "START_FRAME_MISSING",
                    "O frame final exige também um frame inicial para FLF2V.",
                )
            args.extend(["--end-img", str(require_file(str(end_image), "end_image"))])
        if bool(merged.get("offload_to_cpu", True)):
            args.append("--offload-to-cpu")
        if merged.get("extra_args"):
            args.extend(str(value) for value in merged["extra_args"])
        result = await run_command(
            args,
            timeout=int(self.settings.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not native_output.is_file():
            raise EngineExecutionError(
                "ENGINE_OUTPUT_MISSING",
                "sd.cpp terminou sem criar o vídeo nativo solicitado.",
                str(native_output),
            )
        transcode_args: list[str] | None = None
        if native_output != output_path:
            ffmpeg = require_executable(self.settings.get("ffmpeg_path", "ffmpeg"), "ffmpeg")
            transcode = await run_command(
                [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(native_output),
                    "-map_metadata", "-1",
                    "-c:v", str(merged.get("delivery_codec", "libx264")),
                    "-preset", str(merged.get("delivery_preset", "medium")),
                    "-crf", str(int(merged.get("delivery_crf", 17))),
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(output_path),
                ],
                timeout=int(self.settings.get("timeout_seconds", 14400)),
                cancel_check=cancel_check,
                log=log,
            )
            transcode_args = transcode.args
            if not output_path.is_file():
                raise EngineExecutionError("VIDEO_TRANSCODE_FAILED", "FFmpeg não criou o MP4 final", str(output_path))
            native_output.unlink(missing_ok=True)
        return {
            "path": str(output_path),
            "command": result.args,
            "transcode_command": transcode_args,
            "stdout_tail": result.stdout.splitlines()[-20:],
        }
