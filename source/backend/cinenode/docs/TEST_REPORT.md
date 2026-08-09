# Relatório real de testes — 0.2.0

Data: 2026-08-06

## Resultado

```text
pytest -q
43 passed in 6.61s
```

## E2E Chromium

```text
status: passed
console_errors: []
network_errors: []
```

Fluxo: dashboard → Diretor IA → criação de filme por regras → DAG persistido → validação → pré-voo bloqueado por dependências ausentes → catálogo de providers → governança → viewport 1024×768.

Capturas:

- `assets/previews/v0.2.0-e2e/01-dashboard.png`
- `assets/previews/v0.2.0-e2e/02-agent-director.png`
- `assets/previews/v0.2.0-e2e/03-agent-workflow.png`
- `assets/previews/v0.2.0-e2e/04-preflight-blocked.png`
- `assets/previews/v0.2.0-e2e/05-providers.png`
- `assets/previews/v0.2.0-e2e/06-governance.png`
- `assets/previews/v0.2.0-e2e/07-responsive-1024.png`

## O que os 43 testes cobrem

Banco/migrations/WAL; governança; segurança; assets; backup/restore; fila/retry/recuperação; DAG tipado; agente; multirreferência; start/end; provider contracts; Tripo multiview; sd.cpp CLI; malha não vazia; preflight; frontend; FFmpeg real; auditoria de upstream.

## Limite da evidência

Transportes HTTP simulados validam protocolo, não serviço cloud real. Executáveis fake validam argumentos/processamento de retorno, não modelo neural. FFmpeg e Chromium foram reais. Nenhum checkpoint neural foi executado.

## Validação final do codebase

```text
python utilities/validate_package.py --root . --run-smoke
status: passed
checks: 47
failures: []
governance_state: DEGRADED
governance_tasks: 32
```

## Instalação do wheel

O instalador Linux foi executado usando o wheel incluído. Como o índice do executor não oferecia FastAPI, o fallback detectou os pacotes compatíveis do Python hospedeiro, instalou o wheel sem dependências e validou os imports.

```text
avangard_visual-0.2.0-py3-none-any.whl
size: 1545941 bytes
sha256: 71e5244d454e0c365f37a5c0450a34c4a7837a19daef53028faf4f7c1486f47c
/api/health: HTTP 200
version: 0.2.0
```

## ZIP candidato extraído

O ZIP candidato foi testado com `unzip` em pasta limpa:

```text
ZIP integrity: ok
FILE_MANIFEST.sha256: 171/171 aprovados
pytest: 43/43 aprovados
validate_package --run-smoke: passed
install.sh --skip-opensources: passed
/api/health: HTTP 200, version 0.2.0
database_integrity: ok
E2E Chromium: passed
console_errors: []
network_errors: []
```

Esse gate continua sendo de controle/instalação. Não altera o status reprovado da inferência neural.
