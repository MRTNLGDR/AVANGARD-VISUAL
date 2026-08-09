# Architecture

```text
Browser / future Tauri shell
        │ HTTP + SSE
        ▼
FastAPI control plane
 ├─ Director agent + validated graph builder
 ├─ Typed DAG + preflight + persistent queue
 ├─ Provider registry
 │   ├─ local: sd.cpp, ComfyUI, WanGP, Ollama, trellis.cpp, TripoSR
 │   └─ cloud: Freepik, Replicate, fal.ai, Tripo v2, generic REST
 ├─ post: Real-ESRGAN, RIFE, FFmpeg, Blender
 ├─ SQLite WAL + filesystem assets
 └─ governance snapshot/logs/evidence
```

The web server is a control plane. Neural models remain in external binaries/sidecars so a failed model does not corrupt the database and VRAM can be reclaimed between processes.

A graph is validated twice: structural validation checks typed ports/cycles; preflight checks real assets, executable paths, model files, Comfy workflow JSON, cloud key names/endpoints and post-processing engines. Only then may a job enter the queue.

Generated and downloaded outputs are copied into local asset storage and hashed. Remote URLs are not treated as durable results.

The active frontend is a dependency-light custom typed canvas. A React/Vibe migration boundary exists but is not the active runtime and is tracked as an open governance task.
