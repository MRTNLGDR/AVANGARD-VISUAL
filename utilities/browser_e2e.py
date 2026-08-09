#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(url: str, process: subprocess.Popen, log_path: Path) -> None:
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError(f"Server exited early\n{log_path.read_text(errors='replace')}")
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Server timeout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    screenshots = (args.screenshots or root / "docs" / "screenshots").resolve()
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Playwright is required: python -m pip install playwright && playwright install chromium") from exc

    port = free_port()
    with tempfile.TemporaryDirectory(prefix="cinenode-e2e-") as temp:
        temp_path = Path(temp)
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(root / "source" / "backend"),
            "CINENODE_HOME": str(temp_path / "data"),
            "CINENODE_HOST": "127.0.0.1",
            "CINENODE_PORT": str(port),
        })
        log_path = temp_path / "server.log"
        log = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "cinenode", "run", "--no-browser"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        errors: list[str] = []
        network_errors: list[str] = []
        try:
            wait_ready(base, process, log_path)
            with sync_playwright() as playwright:
                executable_path = None
                if not Path(playwright.chromium.executable_path).exists():
                    executable_path = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
                    if not executable_path:
                        raise RuntimeError(
                            "No Chromium executable found. Run `playwright install chromium` or install system Chromium."
                        )
                browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
                page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
                page.on("console", lambda message: errors.append(f"console:{message.type}:{message.text}") if message.type == "error" else None)
                page.on("pageerror", lambda error: errors.append(f"pageerror:{error}"))
                page.on(
                    "response",
                    lambda response: network_errors.append(f"http:{response.status}:{response.url}")
                    if response.status >= 400
                    else None,
                )
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_selector("text=Centro de produção local")
                page.screenshot(path=str(screenshots / "01-dashboard.png"), full_page=True)

                # Exercise the visible AI director form. Planning is deterministic here;
                # this proves UI -> API -> persisted typed DAG, not neural inference.
                page.locator("[data-route='agent']").first.click()
                page.wait_for_selector("text=Diretor IA de produção")
                page.locator("#agent-form textarea[name='brief']").fill(
                    "Filme cinematográfico de produto em dois takes, com continuidade e exportação 4K."
                )
                page.locator("#agent-form select[name='target']").select_option("film")
                page.locator("#agent-form select[name='planner_mode']").select_option("rules")
                if page.locator("#agent-form input[name='use_llm']").is_checked():
                    page.locator("#agent-form input[name='use_llm']").uncheck()
                page.screenshot(path=str(screenshots / "02-agent-director.png"), full_page=True)
                page.locator("#agent-form button[type='submit']").click()
                page.wait_for_selector(".workflow-page")
                page.wait_for_selector("[data-node-id]")
                assert page.locator("[data-node-id]").count() >= 4
                page.screenshot(path=str(screenshots / "03-agent-workflow.png"), full_page=True)

                page.locator("[data-workflow='validate']").click()
                page.wait_for_timeout(250)
                page.locator("[data-workflow='preflight']").click()
                page.wait_for_selector("text=Pré-voo real")
                page.screenshot(path=str(screenshots / "04-preflight-blocked.png"), full_page=True)
                page.locator("[data-close-modal]").first.click()

                page.locator("[data-route='providers']").first.click()
                page.wait_for_selector("text=Providers locais e cloud")
                page.wait_for_selector("#provider-diagnostic-form")
                page.screenshot(path=str(screenshots / "05-providers.png"), full_page=True)

                page.locator("[data-route='governance']").first.click()
                page.wait_for_selector("text=Fonte única:")
                page.wait_for_selector("[data-action='refresh-governance']")
                page.screenshot(path=str(screenshots / "06-governance.png"), full_page=True)

                page.set_viewport_size({"width": 1024, "height": 768})
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector("#app")
                page.screenshot(path=str(screenshots / "07-responsive-1024.png"), full_page=True)
                browser.close()

            filtered = [item for item in errors if "favicon" not in item.lower()]
            network_filtered = [item for item in network_errors if "/favicon.ico" not in item.lower()]
            def portable_path(path: Path) -> str:
                try:
                    return path.relative_to(root).as_posix()
                except ValueError:
                    return str(path)

            report = {
                "status": "passed" if not filtered and not network_filtered else "failed",
                "screenshots": [portable_path(path) for path in sorted(screenshots.glob("*.png"))],
                "console_errors": filtered,
                "network_errors": network_filtered,
                "server_log_tail": log_path.read_text(encoding="utf-8", errors="replace")[-4000:],
            }
            (screenshots / "browser-e2e-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if not filtered and not network_filtered else 1
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
