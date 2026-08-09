from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module(root: Path):
    path = root / "utilities" / "audit_upstream.py"
    spec = importlib.util.spec_from_file_location("audit_upstream", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_upstream_audit_accepts_normal_text(tmp_path: Path):
    module = load_module(Path(__file__).resolve().parents[1])
    (tmp_path / "main.ts").write_text("export const value = 42;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"scripts":{"build":"tsc"}}', encoding="utf-8")
    report = module.scan_repository(tmp_path)
    assert report["status"] == "ACCEPTABLE"
    assert report["summary"]["critical"] == 0


def test_upstream_audit_rejects_hidden_variation_selector(tmp_path: Path):
    module = load_module(Path(__file__).resolve().parents[1])
    # U+FE00 is a non-emoji variation selector used by hidden-source encodings.
    (tmp_path / "main.js").write_text("const payload = 'x\ufe00';\n", encoding="utf-8")
    report = module.scan_repository(tmp_path)
    assert report["status"] == "REJECTED"
    finding = next(item for item in report["findings"] if item["kind"] == "INVISIBLE_UNICODE")
    assert finding["codepoint"] == "U+FE00"


def test_upstream_audit_allows_leading_bom_but_rejects_mid_file_bom(tmp_path: Path):
    module = load_module(Path(__file__).resolve().parents[1])
    (tmp_path / "ok.py").write_text("\ufeffprint('ok')\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("print('a')\n\ufeffprint('b')\n", encoding="utf-8")
    report = module.scan_repository(tmp_path)
    assert report["summary"]["critical"] == 1
    assert report["findings"][0]["path"] == "bad.py"
