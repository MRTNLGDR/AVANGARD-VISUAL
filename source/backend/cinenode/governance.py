from __future__ import annotations

from collections import defaultdict
from typing import Any

from .database import Database
from .util import utc_now


SEED_TASKS: list[dict[str, Any]] = [
    {"id": "OSS-001", "module_id": "OSS", "module_title": "Open source e licenças", "category": "LEGAL", "title": "Auditar repositórios base, licenças e commits", "source_path": "docs/OPEN_SOURCE_INTEGRATION.md", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "OSS-SUPPLY-CHAIN-001", "module_id": "OSS", "module_title": "Open source e licenças", "category": "SECURITY", "title": "Quarentena, varredura de Unicode invisível e promoção atômica de upstreams", "source_path": "utilities/audit_upstream.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "ARCH-001", "module_id": "ARCH", "module_title": "Arquitetura", "category": "ARCHITECTURE", "title": "Definir arquitetura local e responsabilidades dos componentes", "source_path": "docs/ARCHITECTURE.md", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "DB-001", "module_id": "CORE", "module_title": "Núcleo e persistência", "category": "BACKEND", "title": "SQLite, migrations, WAL, CRUD e recuperação", "source_path": "source/backend/cinenode/database.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "DAG-001", "module_id": "CORE", "module_title": "Núcleo e persistência", "category": "ENGINE", "title": "Validar e executar DAG nodal com fila persistente", "source_path": "source/backend/cinenode/workflow.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "ENG-001", "module_id": "ENGINES", "module_title": "Engines locais", "category": "INTEGRATION", "title": "Adaptadores reais para sd.cpp, WanGP, ComfyUI, Real-ESRGAN, RIFE, FFmpeg, Ollama e OpenCode", "source_path": "source/backend/cinenode/engines", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "UI-001", "module_id": "UI", "module_title": "Editor nodal", "category": "FRONTEND", "title": "Editor nodal, projetos, jobs, galeria, engines e configurações", "source_path": "source/backend/cinenode/frontend/app.js", "status": "DONE", "priority": "HIGH", "severity": "MEDIUM"},
    {"id": "GOV-001", "module_id": "GOV", "module_title": "Governança", "category": "GOVERNANCE", "title": "Snapshot único, polling, SSE, tarefas, alertas, logs e changelog", "source_path": "source/backend/cinenode/governance.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "SECURITY-001", "module_id": "SECURITY", "module_title": "Segurança local", "category": "SECURITY", "title": "Host/origin/token, upload, path containment, ZIP restore e subprocessos seguros", "source_path": "docs/SECURITY.md", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "TEST-CORE-001", "module_id": "TEST", "module_title": "Testes automatizados", "category": "TEST", "title": "Executar testes unitários, integração, mídia, segurança e recuperação", "source_path": "TEST_REPORT.md", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "E2E-001", "module_id": "TEST", "module_title": "Testes automatizados", "category": "E2E", "title": "Validar navegador real, persistência, governança e responsividade", "source_path": "assets/previews/v0.2.0-e2e/browser-e2e-report.json", "status": "DONE", "priority": "HIGH", "severity": "MEDIUM"},
    {"id": "WHEEL-001", "module_id": "PACKAGING", "module_title": "Instalação e pacote", "category": "PACKAGING", "title": "Construir e instalar wheel Python do backend", "source_path": "utilities/installers/python", "status": "DONE", "priority": "HIGH", "severity": "MEDIUM"},
    {"id": "INSTALL-001", "module_id": "PACKAGING", "module_title": "Instalação e pacote", "category": "INSTALLATION", "title": "Validar instalação de um clique com wheel e fallback automático de dependências", "source_path": "utilities/install.sh", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "PKG-001", "module_id": "PACKAGING", "module_title": "Instalação e pacote", "category": "PACKAGING", "title": "Scripts Windows/macOS/Linux, Docker, ZIP e checksum", "source_path": "scripts", "status": "DONE", "priority": "HIGH", "severity": "MEDIUM"},
    {"id": "OSS-SYNC-001", "module_id": "OSS", "module_title": "Open source e licenças", "category": "OPERATIONS", "title": "Materializar backups upstream pinados, audits, lock e checksums no ambiente com rede", "source_path": "vendor/opensources", "status": "PENDING", "priority": "HIGH", "severity": "MEDIUM"},
    {"id": "MODEL-001", "module_id": "MODELS", "module_title": "Modelos locais", "category": "OPERATIONS", "title": "Baixar e validar pelo menos um perfil de imagem e um de vídeo no Alienware", "source_path": "docs/MODEL_MATRIX.md", "status": "PENDING", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "GPU-TEST-001", "module_id": "TEST", "module_title": "Validação no hardware-alvo", "category": "TEST", "title": "Executar geração real e benchmark na RTX 4090 Laptop 16 GB", "source_path": "docs/VALIDATION.md", "status": "PENDING", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "TAURI-BUILD-001", "module_id": "PACKAGING", "module_title": "Instalação e pacote", "category": "PACKAGING", "title": "Compilar, testar e assinar o instalador Tauri no Windows", "source_path": "source/desktop/src-tauri", "status": "PENDING", "priority": "HIGH", "severity": "MEDIUM"},
]


SEED_TASKS.extend([
    {"id": "AUDIT-REAL-001", "module_id": "AUDIT", "module_title": "Auditoria de funcionamento real", "category": "AUDIT", "title": "Separar testes de protocolo, controle e inferência neural", "source_path": "docs/AUDIT_REPORT.md", "status": "DONE", "priority": "CRITICAL", "severity": "CRITICAL"},
    {"id": "TYPED-DAG-001", "module_id": "CORE", "module_title": "Núcleo e persistência", "category": "ENGINE", "title": "Expandir catálogo para 24 nós com portas e multiplicidade tipadas", "source_path": "source/backend/cinenode/workflow.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "AGENT-001", "module_id": "AGENT", "module_title": "Diretor IA", "category": "AGENT", "title": "Criar DAG persistente por brief, referências e capacidade do provider", "source_path": "source/backend/cinenode/agent.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "MULTIREF-001", "module_id": "AGENT", "module_title": "Diretor IA", "category": "MEDIA", "title": "Referências múltiplas com papéis character, style, product, composition, multiview e máscara", "source_path": "source/backend/cinenode/schemas.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "VIDEO-FLF-001", "module_id": "VIDEO", "module_title": "Vídeo e filme", "category": "ENGINE", "title": "Start frame e end frame separados com perfil FLF2V e --end-img", "source_path": "source/backend/cinenode/engines/sd_cpp.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "PROVIDERS-001", "module_id": "PROVIDERS", "module_title": "Providers", "category": "INTEGRATION", "title": "Adaptadores Freepik, Replicate, fal.ai, Tripo v2 e REST genérico", "source_path": "source/backend/cinenode/providers/cloud.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "MESH-3D-001", "module_id": "3D", "module_title": "Reconstrução 3D", "category": "ENGINE", "title": "Nós e adaptadores trellis.cpp, TripoSR, Tripo cloud, CLI genérico e Blender", "source_path": "source/backend/cinenode/engines/mesh.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "PREFLIGHT-001", "module_id": "AUDIT", "module_title": "Auditoria de funcionamento real", "category": "VALIDATION", "title": "Pré-voo bloqueia execução sem binário, peso, workflow, chave ou endpoint", "source_path": "source/backend/cinenode/preflight.py", "status": "DONE", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "FRONTEND-002", "module_id": "UI", "module_title": "Editor nodal", "category": "FRONTEND", "title": "Diretor IA, referências tipadas, providers, diagnóstico e pré-voo na interface ativa", "source_path": "source/backend/cinenode/frontend/app.js", "status": "DONE", "priority": "HIGH", "severity": "MEDIUM"},
    {"id": "INFERENCE-IMAGE-001", "module_id": "TEST", "module_title": "Validação no hardware-alvo", "category": "INFERENCE", "title": "Gerar e inspecionar imagem real com peso local no Alienware", "source_path": "docs/VALIDATION.md", "status": "PENDING", "priority": "CRITICAL", "severity": "CRITICAL"},
    {"id": "INFERENCE-VIDEO-001", "module_id": "TEST", "module_title": "Validação no hardware-alvo", "category": "INFERENCE", "title": "Gerar vídeo real T2V, I2V e FLF2V no Alienware", "source_path": "docs/VALIDATION.md", "status": "PENDING", "priority": "CRITICAL", "severity": "CRITICAL"},
    {"id": "INFERENCE-3D-001", "module_id": "TEST", "module_title": "Validação no hardware-alvo", "category": "INFERENCE", "title": "Gerar GLB real com trellis.cpp/TripoSR e validar geometria/textura", "source_path": "docs/VALIDATION.md", "status": "PENDING", "priority": "CRITICAL", "severity": "CRITICAL"},
    {"id": "CLOUD-LIVE-001", "module_id": "PROVIDERS", "module_title": "Providers", "category": "INTEGRATION", "title": "Executar chamadas reais com chaves do usuário em cada provider cloud habilitado", "source_path": "docs/VALIDATION.md", "status": "PENDING", "priority": "CRITICAL", "severity": "HIGH"},
    {"id": "VIBE-EMBED-001", "module_id": "UI", "module_title": "Editor nodal", "category": "UPSTREAM", "title": "Materializar e incorporar fisicamente o package workflow-builder do Vibe ou documentar substituição aprovada", "source_path": "docs/OPEN_SOURCE_INTEGRATION.md", "status": "PENDING", "priority": "HIGH", "severity": "HIGH"},
])

SEED_ALERTS: list[dict[str, Any]] = [
    {"id": "OSS-GAP-001", "severity": "HIGH", "status": "RESOLVED", "kind": "DEPENDENCY", "module_id": "OSS", "fact": "Os três repositórios solicitados são complementares, não um motor local completo.", "action": "Resolvido pela separação de responsabilidades e integração de sd.cpp, FFmpeg, Real-ESRGAN, RIFE, Ollama e sidecars opcionais."},
    {"id": "OSS-SUPPLY-CHAIN-001", "severity": "HIGH", "status": "RESOLVED", "kind": "SECURITY", "module_id": "OSS", "fact": "Clones upstream podem carregar código oculto ou scripts de instalação perigosos.", "action": "Clone em quarentena, commit pinado, auditoria estática, relatório, checksum e promoção atômica antes de uso."},
    {"id": "INSTALL-GAP-001", "severity": "HIGH", "status": "RESOLVED", "kind": "INSTALLATION", "module_id": "PACKAGING", "fact": "O instalador dependia de atualização de setuptools e de um índice capaz de fornecer todo o runtime.", "action": "O instalador agora prefere o wheel, evita upgrades desnecessários e usa fallback automático validado para pacotes compatíveis do Python hospedeiro quando o índice está indisponível."},
    {"id": "OSS-SYNC-BLOCK-001", "severity": "MEDIUM", "status": "OPEN", "kind": "ENVIRONMENT", "module_id": "OSS", "fact": "O executor de entrega não possui DNS externo para materializar os clones completos no acervo.", "action": "Executar bootstrap-opensources no Alienware; o processo falha fechado e produz manifest.lock, audits e checksums."},
    {"id": "BUILD-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "ENVIRONMENT", "module_id": "PACKAGING", "fact": "Windows e RTX 4090 Laptop com 16 GB foram detectados; Rust/Cargo e assinatura do instalador ainda não foram validados.", "action": "Executar utilities/build-tauri.ps1 -Clean e os gates de GPU no Alienware; não considerar o instalador nativo aprovado antes disso."},
    {"id": "LICENSE-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "LICENSE", "module_id": "OSS", "fact": "WanGP usa WanGP Community License 2.0, com restrições de incorporação, white-label e monetização.", "action": "Manter WanGP externo, opcional, não redistribuído e exigir aceite explícito."},
    {"id": "MODEL-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "MODEL", "module_id": "MODELS", "fact": "Pesos multi-GB não foram baixados nem executados neste ambiente.", "action": "Baixar pelos bundles com SHA-256, aceitar licenças aplicáveis e validar geração no hardware-alvo."},
    {"id": "GPU-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "PERFORMANCE", "module_id": "TEST", "fact": "Tempo, VRAM, temperatura e estabilidade CUDA ainda não foram medidos na RTX 4090 Laptop 16 GB.", "action": "Executar benchmark documentado de imagem, vídeo, upscale e exportação no Alienware."},
]


SEED_ALERTS.extend([
    {"id": "OLD-INFERENCE-CLAIM-001", "severity": "CRITICAL", "status": "RESOLVED", "kind": "AUDIT", "module_id": "AUDIT", "fact": "A versão anterior aprovava banco/API/E2E sem executar modelo neural e isso foi apresentado de forma excessivamente positiva.", "action": "A v0.2 separa protocolos de inferência, adiciona pré-voo e mantém os gates de inferência abertos."},
    {"id": "INFERENCE-NOT-VALIDATED-001", "severity": "CRITICAL", "status": "OPEN", "kind": "INFERENCE", "module_id": "TEST", "fact": "A RTX 4090 Laptop foi detectada, mas nenhum peso local está instalado; nenhuma imagem, vídeo ou malha neural foi inferida nesta máquina.", "action": "Baixar um bundle, executar os três gates e anexar arquivos, logs, VRAM, duração e hashes."},
    {"id": "CLOUD-LIVE-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "PROVIDER", "module_id": "PROVIDERS", "fact": "Os contratos Freepik, Replicate, fal.ai e Tripo foram testados com transportes simulados, não com chaves reais.", "action": "Habilitar individualmente, executar diagnóstico real e preservar outputs localmente."},
    {"id": "VIBE-RUNTIME-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "UPSTREAM", "module_id": "UI", "fact": "O runtime ativo é um canvas tipado próprio; o package ReactFlow do Vibe Workflow ainda não foi materializado/incorporado.", "action": "Sincronizar upstream pinado e concluir integração física ou assumir formalmente o canvas substituto."},
    {"id": "MESH-LIVE-GAP-001", "severity": "HIGH", "status": "OPEN", "kind": "3D", "module_id": "3D", "fact": "Adaptadores e instaladores 3D existem, mas trellis.cpp/TripoSR não foram instalados nem executados neste ambiente.", "action": "Instalar no Alienware, baixar pesos, gerar GLB e validar arquivo não vazio, materiais e preview."},
])

SEED_DOCUMENTS = [
    ("README", "/docs/README.md"),
    ("Quickstart", "/docs/QUICKSTART.md"),
    ("API", "/docs/API.md"),
    ("Arquitetura", "/docs/ARCHITECTURE.md"),
    ("Matriz de modelos", "/docs/MODEL_MATRIX.md"),
    ("Integração open source", "/docs/OPEN_SOURCE_INTEGRATION.md"),
    ("Segurança", "/docs/SECURITY.md"),
    ("Recuperação", "/docs/RECOVERY.md"),
    ("Validação", "/docs/VALIDATION.md"),
    ("Relatório de testes", "/docs/TEST_REPORT.md"),
    ("Auditoria final", "/docs/AUDIT_REPORT.md"),
]


def seed_governance(db: Database) -> None:
    now = utc_now()
    with db.transaction() as connection:
        for task in SEED_TASKS:
            connection.execute(
                "INSERT INTO governance_tasks(id,module_id,module_title,category,title,source_path,source_line,status,priority,severity,evidence_json,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "module_id=excluded.module_id,module_title=excluded.module_title,category=excluded.category,title=excluded.title," 
                "source_path=excluded.source_path,priority=excluded.priority,severity=excluded.severity",
                (
                    task["id"], task["module_id"], task["module_title"], task["category"], task["title"],
                    task["source_path"], 1, task["status"], task["priority"], task["severity"], "[]", now,
                ),
            )
        for alert in SEED_ALERTS:
            connection.execute(
                "INSERT INTO governance_alerts(id,severity,status,kind,fact,action,module_id,evidence_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET severity=excluded.severity,kind=excluded.kind,fact=excluded.fact,action=excluded.action,module_id=excluded.module_id",
                (alert["id"], alert["severity"], alert["status"], alert["kind"], alert["fact"], alert["action"], alert["module_id"], "[]", now, now),
            )
        for name, link in SEED_DOCUMENTS:
            connection.execute(
                "INSERT INTO governance_documents(name,link,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET link=excluded.link,updated_at=excluded.updated_at",
                (name, link, now),
            )
        exists = connection.execute("SELECT COUNT(*) FROM governance_changes").fetchone()[0]
        if not exists:
            connection.executemany(
                "INSERT INTO governance_changes(release,category,description,source_line,created_at) VALUES(?,?,?,?,?)",
                [
                    ("0.3.0", "Changed", "Identidade Avangard Visual, dashboard de produção e organização de assets, modelos, utilidades, vendor e arquivo.", 1, now),
                    ("0.2.0", "Changed", "Auditoria de inferência, agente, multirreferência, FLF2V, providers, 3D e pré-voo real.", 1, now),
                ],
            )


def log_governance(db: Database, level: str, event: str, detail: Any) -> None:
    db.execute(
        "INSERT INTO governance_logs(created_at,level,event,detail_json) VALUES(?,?,?,?)",
        (utc_now(), level, event, db.dump_json(detail)),
    )


def update_task(db: Database, task_id: str, status: str, evidence: Any | None = None) -> bool:
    row = db.query_one("SELECT evidence_json FROM governance_tasks WHERE id=?", (task_id,))
    if not row:
        return False
    items = db.load_json(row["evidence_json"], [])
    if evidence is not None:
        items.append({"at": utc_now(), "detail": evidence})
    db.execute(
        "UPDATE governance_tasks SET status=?, evidence_json=?, updated_at=? WHERE id=?",
        (status, db.dump_json(items), utc_now(), task_id),
    )
    log_governance(db, "INFO", "governance.task.updated", {"task_id": task_id, "status": status})
    return True


def set_alert_status(db: Database, alert_id: str, status: str, evidence: Any | None = None) -> bool:
    row = db.query_one("SELECT evidence_json FROM governance_alerts WHERE id=?", (alert_id,))
    if not row:
        return False
    items = db.load_json(row["evidence_json"], [])
    if evidence is not None:
        items.append({"at": utc_now(), "detail": evidence})
    db.execute(
        "UPDATE governance_alerts SET status=?, evidence_json=?, updated_at=? WHERE id=?",
        (status, db.dump_json(items), utc_now(), alert_id),
    )
    return True


def read_governance_snapshot(db: Database) -> dict[str, Any]:
    tasks = db.query(
        "SELECT id,category,title,source_path,source_line,status,module_id,module_title FROM governance_tasks ORDER BY status DESC, priority DESC, id"
    )
    alerts = db.query(
        "SELECT id,severity,status,kind,fact,action FROM governance_alerts ORDER BY CASE severity WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END DESC, updated_at DESC"
    )
    changes = db.query(
        "SELECT release,category,description,source_line FROM governance_changes ORDER BY id DESC LIMIT 100"
    )
    log_rows = db.query(
        "SELECT created_at,level,event,detail_json FROM governance_logs ORDER BY id DESC LIMIT 200"
    )
    documents = db.query("SELECT name,link,updated_at FROM governance_documents ORDER BY name")

    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"done": 0, "total": 0})
    for task in tasks:
        key = (task.pop("module_id"), task.pop("module_title"))
        grouped[key]["total"] += 1
        grouped[key]["done"] += int(task["status"] == "DONE")

    modules = [
        {"module_id": key[0], "module_title": key[1], "done": value["done"], "total": value["total"]}
        for key, value in sorted(grouped.items())
    ]
    total = len(tasks)
    done = sum(1 for task in tasks if task["status"] == "DONE")
    pending = total - done
    open_alerts = sum(1 for alert in alerts if alert["status"] == "OPEN")
    critical_or_high = any(
        alert["status"] == "OPEN" and alert["severity"] in {"CRITICAL", "HIGH"}
        for alert in alerts
    )
    state = "EMPTY" if total == 0 else ("DEGRADED" if critical_or_high else "READY")
    logs = [
        {"created_at": row["created_at"], "level": row["level"], "event": row["event"], "detail": db.load_json(row["detail_json"], {})}
        for row in log_rows
    ]
    return {
        "generatedAt": utc_now(),
        "state": state,
        "summary": {
            "totalTasks": total,
            "doneTasks": done,
            "pendingTasks": pending,
            "openAlerts": open_alerts,
            "documents": len(documents),
            "progressPercent": round((done / total * 100.0) if total else 0.0, 2),
        },
        "modules": modules,
        "tasks": tasks,
        "alerts": alerts,
        "changelog": changes,
        "logs": logs,
        "documents": documents,
    }
