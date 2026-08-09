# Estrutura do Avangard Visual

```text
MAIN/
|-- source/backend/cinenode/   # produto executável: API, DAG, agentes e frontend
|-- source/desktop/            # shell instalável Tauri
|-- assets/                    # marca, screenshots e previews versionados
|-- models/                    # catálogo e gerenciador; pesos ficam em data/models
|-- utilities/                 # instalação, execução, build, auditoria e validação
|-- vendor/                    # integrações open source controladas
|-- governance/                # tarefas, roadmap e alertas auditáveis
|-- docs/                      # arquitetura, API, segurança e operação
|-- tests/                     # suíte automatizada
|-- data/                      # estado local; arquivos pesados não entram no Git
`-- archive/                   # releases, relatórios e protótipos preservados
```

## Fonte canônica

O frontend servido e empacotado fica em `source/backend/cinenode/frontend`. O backend continua usando o módulo interno `cinenode` por compatibilidade com banco, CLI e backups; o nome visível do produto é apenas **Avangard Visual**.

## Estados de IA

- `integrated`: adapter e perfil existem.
- `downloaded`: todos os arquivos esperados passaram por checksum.
- `verified`: uma inferência neural real produziu um artefato válido nesta máquina.

Esses estados não são intercambiáveis. A interface nunca deve classificar um modelo como pronto apenas porque a API, o binário ou um mock respondeu.
