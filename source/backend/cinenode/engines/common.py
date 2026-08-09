from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Sequence


class EngineExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


LogCallback = Callable[[str, str], Awaitable[None]]
CancelCheck = Callable[[], bool]


def find_executable(configured: str | None) -> str | None:
    if not configured:
        return None
    expanded = os.path.expandvars(os.path.expanduser(configured))
    path = Path(expanded)
    if path.is_file():
        return str(path.resolve())
    return shutil.which(expanded)


def require_executable(configured: str | None, engine_id: str) -> str:
    executable = find_executable(configured)
    if not executable:
        raise EngineExecutionError(
            "ENGINE_BINARY_MISSING",
            f"O binário de {engine_id} não foi encontrado.",
            f"Configure o caminho real do binário em Configurações > Engines. Valor atual: {configured!r}",
        )
    return executable


def require_file(value: str | None, label: str) -> Path:
    if not value:
        raise EngineExecutionError("MODEL_PATH_MISSING", f"Caminho ausente: {label}")
    path = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
    if not path.is_file():
        raise EngineExecutionError(
            "MODEL_FILE_MISSING",
            f"Arquivo de modelo não encontrado: {label}",
            str(path),
        )
    return path


async def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 14400,
    cancel_check: CancelCheck | None = None,
    log: LogCallback | None = None,
) -> CommandResult:
    if not args:
        raise ValueError("Command cannot be empty")
    process = await asyncio.create_subprocess_exec(
        *[str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    async def consume(stream: asyncio.StreamReader | None, name: str, sink: list[str]) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            sink.append(text)
            if log:
                await log(name, text)

    consumers = [
        asyncio.create_task(consume(process.stdout, "stdout", stdout_parts)),
        asyncio.create_task(consume(process.stderr, "stderr", stderr_parts)),
    ]
    started = asyncio.get_running_loop().time()
    try:
        while process.returncode is None:
            if cancel_check and cancel_check():
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=8)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                raise EngineExecutionError("JOB_CANCELLED", "Execução cancelada pelo usuário")
            if asyncio.get_running_loop().time() - started > timeout:
                process.kill()
                await process.wait()
                raise EngineExecutionError(
                    "ENGINE_TIMEOUT",
                    f"O processo excedeu o limite de {timeout} segundos.",
                    " ".join(str(arg) for arg in args),
                )
            await asyncio.sleep(0.2)
        await asyncio.gather(*consumers)
    finally:
        for task in consumers:
            if not task.done():
                task.cancel()
    result = CommandResult(
        args=[str(arg) for arg in args],
        returncode=int(process.returncode or 0),
        stdout="\n".join(stdout_parts),
        stderr="\n".join(stderr_parts),
    )
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).splitlines()[-30:])
        raise EngineExecutionError(
            "ENGINE_PROCESS_FAILED",
            f"O processo terminou com código {result.returncode}.",
            tail,
        )
    return result
