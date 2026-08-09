from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config")
    parser.add_argument("--cli-arg", action="append", default=[])
    args = parser.parse_args()

    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    from shared.api import init  # type: ignore[import-not-found]

    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    session = init(
        root=root,
        config_path=Path(args.config).resolve() if args.config else None,
        output_dir=Path(args.output_dir).resolve(),
        cli_args=args.cli_arg,
        console_output=True,
        console_isatty=False,
    )
    job = session.submit_task(settings)
    result = job.result()
    payload = {
        "success": bool(result.success),
        "generated_files": [str(path) for path in (result.generated_files or [])],
        "errors": [
            {"message": str(getattr(error, "message", error)), "type": type(error).__name__}
            for error in (result.errors or [])
        ],
    }
    Path(args.result).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
