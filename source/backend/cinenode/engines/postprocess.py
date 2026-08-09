from __future__ import annotations

import json
import shutil
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from .common import EngineExecutionError, LogCallback, CancelCheck, find_executable, require_executable, require_file, run_command


class PostProcessEngines:
    def __init__(self, realesrgan: dict[str, Any], rife: dict[str, Any], ffmpeg: dict[str, Any]):
        self.realesrgan = realesrgan
        self.rife = rife
        self.ffmpeg = ffmpeg

    async def status(self) -> list[dict[str, Any]]:
        statuses = []
        for engine_id, settings, key in (
            ("realesrgan", self.realesrgan, "binary_path"),
            ("rife", self.rife, "binary_path"),
            ("ffmpeg", self.ffmpeg, "binary_path"),
        ):
            executable = find_executable(settings.get(key))
            if not executable:
                statuses.append({"engine_id": engine_id, "available": False, "version": None, "detail": f"{settings.get(key)!r} não encontrado"})
                continue
            version = "installed"
            if engine_id == "ffmpeg":
                try:
                    result = await run_command([executable, "-version"], timeout=20)
                    version = result.stdout.splitlines()[0][:300]
                except Exception as exc:
                    version = str(exc)[:300]
            statuses.append({"engine_id": engine_id, "available": True, "version": version, "detail": executable})
        return statuses

    async def upscale_image(
        self,
        input_path: Path,
        output_path: Path,
        *,
        scale: int = 4,
        model: str = "realesrgan-x4plus",
        tile: int = 0,
        gpu_id: int = 0,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.realesrgan.get("binary_path"), "Real-ESRGAN")
        input_path = require_file(str(input_path), "input_image")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = [
            executable, "-i", str(input_path), "-o", str(output_path), "-n", model,
            "-s", str(int(scale)), "-g", str(int(gpu_id)), "-f", output_path.suffix.lstrip(".") or "png",
        ]
        models_path = self.realesrgan.get("models_path")
        if models_path:
            args.extend(["-m", str(Path(models_path).expanduser().resolve())])
        if tile > 0:
            args.extend(["-t", str(int(tile))])
        result = await run_command(
            args,
            timeout=int(self.realesrgan.get("timeout_seconds", 14400)),
            cancel_check=cancel_check,
            log=log,
        )
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Real-ESRGAN não criou a saída", str(output_path))
        return {"path": str(output_path), "command": result.args}

    async def resize_image_ffmpeg(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        height: int,
        *,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        input_path = require_file(str(input_path), "input_image")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = [
            executable, "-hide_banner", "-y", "-i", str(input_path),
            "-vf", f"scale={int(width)}:{int(height)}:flags=lanczos",
            "-frames:v", "1", str(output_path),
        ]
        result = await run_command(args, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "FFmpeg não criou a imagem", str(output_path))
        return {"path": str(output_path), "command": result.args, "method": "lanczos_non_ai"}

    async def _probe_video(self, input_path: Path, *, log: LogCallback | None = None) -> dict[str, Any]:
        probe = require_executable(self.ffmpeg.get("probe_path", "ffprobe"), "FFprobe")
        result = await run_command(
            [
                probe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate,r_frame_rate,nb_frames,width,height,duration",
                "-of", "json",
                str(input_path),
            ],
            timeout=120,
            log=log,
        )
        try:
            stream = json.loads(result.stdout)["streams"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise EngineExecutionError("MEDIA_PROBE_FAILED", "FFprobe não retornou metadados de vídeo válidos", result.stdout[-2000:]) from exc

        rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
        try:
            source_fps = float(Fraction(str(rate)))
        except (ValueError, ZeroDivisionError):
            source_fps = 0.0
        stream["source_fps"] = source_fps
        return stream

    async def interpolate_video(
        self,
        input_path: Path,
        output_path: Path,
        *,
        target_fps: int = 60,
        engine: str = "rife",
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        input_path = require_file(str(input_path), "input_video")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target_fps = int(target_fps)
        if target_fps < 1 or target_fps > 240:
            raise EngineExecutionError("INVALID_TARGET_FPS", "FPS alvo deve estar entre 1 e 240", str(target_fps))

        if engine == "rife":
            ffmpeg = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
            executable = require_executable(self.rife.get("binary_path"), "RIFE")
            metadata = await self._probe_video(input_path, log=log)
            source_fps = float(metadata.get("source_fps") or 0.0)
            if source_fps <= 0:
                raise EngineExecutionError("MEDIA_PROBE_FAILED", "Não foi possível determinar o FPS de origem", str(input_path))
            if target_fps <= source_fps:
                raise EngineExecutionError(
                    "INVALID_INTERPOLATION_FPS",
                    "RIFE só é usado para aumentar o FPS; escolha um FPS maior que o original ou use FFmpeg.",
                    f"source={source_fps:.3f}, target={target_fps}",
                )

            with tempfile.TemporaryDirectory(prefix="cinenode-rife-", dir=output_path.parent) as temp_dir:
                work_dir = Path(temp_dir)
                frames_in = work_dir / "frames-in"
                frames_out = work_dir / "frames-out"
                frames_in.mkdir()
                frames_out.mkdir()

                extract_args = [
                    ffmpeg, "-hide_banner", "-y", "-i", str(input_path),
                    "-vsync", "0", str(frames_in / "%08d.png"),
                ]
                await run_command(
                    extract_args,
                    timeout=int(self.ffmpeg.get("timeout_seconds", 14400)),
                    cancel_check=cancel_check,
                    log=log,
                )
                input_frames = len(list(frames_in.glob("*.png")))
                if input_frames < 2:
                    raise EngineExecutionError("MEDIA_DECODE_FAILED", "O vídeo precisa ter ao menos dois frames", str(input_path))
                target_frames = max(input_frames + 1, round(input_frames * target_fps / source_fps))

                args = [
                    executable,
                    "-i", str(frames_in),
                    "-o", str(frames_out),
                    "-n", str(target_frames),
                    "-f", "%08d.png",
                ]
                model_path = self.rife.get("models_path")
                if model_path:
                    args.extend(["-m", str(Path(model_path).expanduser().resolve())])
                result = await run_command(
                    args,
                    timeout=int(self.rife.get("timeout_seconds", 14400)),
                    cancel_check=cancel_check,
                    log=log,
                )
                produced_frames = len(list(frames_out.glob("*.png")))
                if produced_frames < 2:
                    raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "RIFE não produziu frames interpolados", str(frames_out))

                encode_args = [
                    ffmpeg, "-hide_banner", "-y",
                    "-framerate", str(target_fps),
                    "-i", str(frames_out / "%08d.png"),
                    "-i", str(input_path),
                    "-map", "0:v:0", "-map", "1:a?",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(output_path),
                ]
                encode_result = await run_command(
                    encode_args,
                    timeout=int(self.ffmpeg.get("timeout_seconds", 14400)),
                    cancel_check=cancel_check,
                    log=log,
                )
                command = {"rife": result.args, "encode": encode_result.args}
        elif engine == "ffmpeg":
            executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
            args = [
                executable, "-hide_banner", "-y", "-i", str(input_path),
                "-vf", f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir",
                "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "copy", str(output_path),
            ]
            result = await run_command(args, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
            command = result.args
        else:
            raise EngineExecutionError("INVALID_INTERPOLATION_ENGINE", f"Engine de interpolação não suportada: {engine}")

        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Interpolação não criou a saída", str(output_path))
        return {"path": str(output_path), "command": command, "engine": engine, "target_fps": target_fps}

    async def upscale_video(
        self,
        input_path: Path,
        output_path: Path,
        work_dir: Path,
        *,
        scale: int = 2,
        model: str = "realesrgan-x4plus",
        target_fps: int | None = None,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        ffmpeg = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        realesrgan = require_executable(self.realesrgan.get("binary_path"), "Real-ESRGAN")
        input_path = require_file(str(input_path), "input_video")
        frames_in = work_dir / "frames-in"
        frames_out = work_dir / "frames-out"
        shutil.rmtree(work_dir, ignore_errors=True)
        frames_in.mkdir(parents=True)
        frames_out.mkdir(parents=True)
        extract = [ffmpeg, "-hide_banner", "-y", "-i", str(input_path), str(frames_in / "%08d.png")]
        await run_command(extract, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        upscale = [
            realesrgan, "-i", str(frames_in), "-o", str(frames_out), "-n", model,
            "-s", str(int(scale)), "-g", "0", "-f", "png",
        ]
        models_path = self.realesrgan.get("models_path")
        if models_path:
            upscale.extend(["-m", str(Path(models_path).expanduser().resolve())])
        await run_command(upscale, timeout=int(self.realesrgan.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        fps = target_fps or 24
        output_path.parent.mkdir(parents=True, exist_ok=True)
        encode = [
            ffmpeg, "-hide_banner", "-y", "-framerate", str(int(fps)), "-i", str(frames_out / "%08d.png"),
            "-i", str(input_path), "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-preset", "slow", "-crf", "15",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-shortest", str(output_path),
        ]
        result = await run_command(encode, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Upscale de vídeo não criou saída", str(output_path))
        return {"path": str(output_path), "command": result.args, "scale": scale}

    async def resize_video_ffmpeg(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        height: int,
        *,
        codec: str = "h265",
        crf: int = 16,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        input_path = require_file(str(input_path), "input_video")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        codec_args = {
            "h264": ["-c:v", "libx264", "-preset", "slow", "-crf", str(int(crf)), "-pix_fmt", "yuv420p"],
            "h265": ["-c:v", "libx265", "-preset", "slow", "-crf", str(int(crf)), "-pix_fmt", "yuv420p10le"],
        }
        if codec not in codec_args:
            raise EngineExecutionError("INVALID_CODEC", f"Codec de resize não suportado: {codec}")
        args = [
            executable, "-hide_banner", "-y", "-i", str(input_path),
            "-vf", f"scale={int(width)}:{int(height)}:flags=lanczos",
            *codec_args[codec], "-c:a", "copy", "-movflags", "+faststart", str(output_path),
        ]
        result = await run_command(args, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "FFmpeg não criou o vídeo redimensionado", str(output_path))
        return {"path": str(output_path), "command": result.args, "width": int(width), "height": int(height), "method": "lanczos_non_ai"}

    async def extract_frame(
        self,
        input_path: Path,
        output_path: Path,
        *,
        at_seconds: float = 0.0,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        input_path = require_file(str(input_path), "input_video")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = await run_command(
            [executable, "-hide_banner", "-y", "-ss", str(max(0.0, float(at_seconds))), "-i", str(input_path), "-frames:v", "1", str(output_path)],
            timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log,
        )
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "FFmpeg não extraiu o frame", str(output_path))
        return {"path": str(output_path), "command": result.args, "at_seconds": float(at_seconds)}

    async def concat_videos(
        self,
        inputs: list[Path],
        output_path: Path,
        *,
        transition_seconds: float = 0.0,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        verified = [require_file(str(path), "input_video") for path in inputs]
        if len(verified) < 2:
            raise EngineExecutionError("VIDEO_INPUT_MISSING", "Concatenação precisa de pelo menos dois vídeos")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if transition_seconds <= 0:
            manifest = output_path.parent / f".{output_path.stem}-concat.txt"
            manifest.write_text("".join(f"file '{str(path).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n" for path in verified), encoding="utf-8")
            try:
                result = await run_command(
                    [executable, "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", str(output_path)],
                    timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log,
                )
            finally:
                manifest.unlink(missing_ok=True)
        else:
            raise EngineExecutionError(
                "TRANSITION_MODE_UNAVAILABLE",
                "Esta versão validada monta takes com corte. Transições não são expostas até o pipeline xfade de áudio e vídeo passar no gate real.",
                f"transition_seconds={transition_seconds}",
            )
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Concatenação não criou vídeo", str(output_path))
        return {"path": str(output_path), "command": result.args, "inputs": [str(path) for path in verified]}

    async def mix_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        *,
        audio_volume: float = 1.0,
        replace_original: bool = False,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        video_path = require_file(str(video_path), "input_video")
        audio_path = require_file(str(audio_path), "input_audio")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = [executable, "-hide_banner", "-y", "-i", str(video_path), "-i", str(audio_path)]
        if replace_original:
            args.extend(["-map", "0:v:0", "-map", "1:a:0", "-filter:a", f"volume={float(audio_volume)}"])
        else:
            args.extend(["-filter_complex", f"[0:a]volume=1[a0];[1:a]volume={float(audio_volume)}[a1];[a0][a1]amix=inputs=2:duration=first[a]", "-map", "0:v:0", "-map", "[a]"])
        args.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-shortest", str(output_path)])
        result = await run_command(args, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Mixagem não criou vídeo", str(output_path))
        return {"path": str(output_path), "command": result.args}

    async def export_media(
        self,
        input_path: Path,
        output_path: Path,
        *,
        codec: str = "h264",
        crf: int = 16,
        fps: int | None = None,
        cancel_check: CancelCheck | None = None,
        log: LogCallback | None = None,
    ) -> dict[str, Any]:
        executable = require_executable(self.ffmpeg.get("binary_path", "ffmpeg"), "FFmpeg")
        input_path = require_file(str(input_path), "input_media")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        codec_args = {
            "h264": ["-c:v", "libx264", "-preset", "slow", "-crf", str(int(crf)), "-pix_fmt", "yuv420p"],
            "h265": ["-c:v", "libx265", "-preset", "slow", "-crf", str(int(crf)), "-pix_fmt", "yuv420p10le"],
            "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
            "av1": ["-c:v", "libsvtav1", "-crf", str(int(crf)), "-preset", "6", "-pix_fmt", "yuv420p10le"],
        }
        if codec not in codec_args:
            raise EngineExecutionError("INVALID_CODEC", f"Codec não suportado: {codec}")
        args = [executable, "-hide_banner", "-y", "-i", str(input_path)]
        if fps:
            args.extend(["-r", str(int(fps))])
        args.extend(codec_args[codec])
        args.extend(["-c:a", "aac", "-b:a", "320k", str(output_path)])
        result = await run_command(args, timeout=int(self.ffmpeg.get("timeout_seconds", 14400)), cancel_check=cancel_check, log=log)
        if not output_path.is_file():
            raise EngineExecutionError("ENGINE_OUTPUT_MISSING", "Exportação não criou saída", str(output_path))
        return {"path": str(output_path), "command": result.args, "codec": codec}
