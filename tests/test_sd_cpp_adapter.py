from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from cinenode.engines.sd_cpp import StableDiffusionCppEngine


@pytest.mark.asyncio
@pytest.mark.media
@pytest.mark.skipif(os.name == "nt" or shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="POSIX adapter contract requires Bash and FFmpeg")
async def test_sd_cpp_video_adapter_transcodes_native_avi(tmp_path: Path):
    fake = tmp_path / "sd-cli"
    fake.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
out=''
fps=16
while [[ $# -gt 0 ]]; do
  case \"$1\" in
    -o) out=\"$2\"; shift 2 ;;
    --fps) fps=\"$2\"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n \"$out\" ]]
ffmpeg -hide_banner -loglevel error -y -f lavfi -i color=c=blue:s=64x48:d=0.25 -r \"$fps\" -c:v mjpeg \"$out\"
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    output = tmp_path / "result.mp4"
    engine = StableDiffusionCppEngine(
        {"binary_path": str(fake), "ffmpeg_path": shutil.which("ffmpeg"), "timeout_seconds": 30}
    )
    result = await engine.generate_video(
        {"diffusion_model": str(model), "defaults": {"width": 64, "height": 48, "frames": 9, "fps": 20}},
        "test prompt",
        "",
        output,
        {"steps": 1, "offload_to_cpu": False},
    )
    assert output.is_file()
    assert not output.with_suffix(".native.avi").exists()
    assert result["path"] == str(output)
    assert result["transcode_command"]
    assert str(output.with_suffix(".native.avi")) in result["command"]
    probe = os.popen(f'ffprobe -v error -show_entries format=format_name -of default=nw=1:nk=1 "{output}"').read().strip()
    assert "mp4" in probe


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX adapter contract requires Bash")
async def test_sd_cpp_img2img_contract_passes_init_image_and_strength(tmp_path: Path):
    fake = tmp_path / "sd-cli"
    captured = tmp_path / "args.txt"
    fake.write_text(
        f'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "{captured}"
out=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$out" ]]
printf 'not-a-real-inference-image' > "$out"
''',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    output = tmp_path / "edited.png"
    engine = StableDiffusionCppEngine({"binary_path": str(fake), "timeout_seconds": 30})
    result = await engine.generate_image(
        {"diffusion_model": str(model), "defaults": {"width": 64, "height": 48}},
        "edit",
        "",
        output,
        {"steps": 1, "strength": 0.42, "offload_to_cpu": False},
        input_image=source,
    )
    args = captured.read_text(encoding="utf-8").splitlines()
    assert output.is_file()
    assert args[args.index("-i") + 1] == str(source)
    assert args[args.index("--strength") + 1] == "0.42"
    assert result["path"] == str(output)


@pytest.mark.asyncio
@pytest.mark.media
@pytest.mark.skipif(os.name == "nt" or shutil.which("ffmpeg") is None, reason="POSIX adapter contract requires Bash and FFmpeg")
async def test_sd_cpp_flf_contract_passes_start_and_end_frames(tmp_path: Path):
    fake = tmp_path / "sd-cli"
    captured = tmp_path / "args.txt"
    fake.write_text(
        f'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "{captured}"
out=''
fps=16
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    --fps) fps="$2"; shift 2 ;;
    *) shift ;;
  esac
done
ffmpeg -hide_banner -loglevel error -y -f lavfi -i color=c=red:s=64x48:d=0.2 -r "$fps" -c:v mjpeg "$out"
''',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    model = tmp_path / "flf.gguf"
    model.write_bytes(b"model")
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    start.write_bytes(b"start")
    end.write_bytes(b"end")
    output = tmp_path / "flf.mp4"
    engine = StableDiffusionCppEngine({"binary_path": str(fake), "ffmpeg_path": shutil.which("ffmpeg"), "timeout_seconds": 30})
    await engine.generate_video(
        {"diffusion_model": str(model), "defaults": {"width": 64, "height": 48, "frames": 9, "fps": 16}},
        "transition",
        "",
        output,
        {"steps": 1, "offload_to_cpu": False},
        input_image=start,
        end_image=end,
    )
    args = captured.read_text(encoding="utf-8").splitlines()
    assert args[args.index("-i") + 1] == str(start)
    assert args[args.index("--end-img") + 1] == str(end)
    assert output.is_file()
