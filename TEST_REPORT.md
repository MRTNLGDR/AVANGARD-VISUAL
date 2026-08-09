# Relatório de validação - Avangard Visual 0.3.0

Data: 2026-08-09  
Máquina: Alienware, Windows, Intel Core i9-14900HX, NVIDIA GeForce RTX 4090 Laptop GPU com 16 GB de VRAM  
Runtime: Python 3.12, FastAPI, SQLite local

## Resultados executados

| Gate | Resultado | Evidência |
|---|---|---|
| Instalação de um clique | Aprovado | `install.ps1 -SkipOpenSources` instalou `avangard-visual 0.3.0` e inicializou o banco |
| API local | Aprovado | `/api/health` respondeu HTTP 200, `ready: true`, versão `0.3.0` |
| Interface real | Aprovado | Dashboard carregado no navegador interno, sem erros de console |
| Testes Python | Aprovado | `40 passed, 3 skipped` em 49,73 s |
| Backup Windows | Aprovado | Handles SQLite fechados explicitamente e restauração sincronizada com arquivo gravável |
| Catálogo de modelos | Aprovado | Quatro bundles listados e 14 arquivos ausentes reportados corretamente |
| Inferência neural | Não executada | Nenhum peso local está instalado em `data/models` |

## Testes ignorados

Três testes de contrato do adapter `stable-diffusion.cpp` criam executáveis Bash temporários. Eles foram marcados como POSIX e ignorados no Windows. O adapter não foi classificado como inferência validada por causa disso.

## Correções encontradas durante a execução

- O instalador não preparava `setuptools` e `wheel` antes do build editável.
- O instalador apontava para um caminho duplicado de wheels.
- A inicialização não propagava falha do comando `cinenode init`.
- A carga inicial do changelog SQLite usava `execute` com duas listas de parâmetros.
- O backup deixava conexões SQLite temporárias abertas no Windows.
- A restauração chamava `fsync` em um descritor aberto somente para leitura.
- Fixtures e testes ainda apontavam para `source/frontend` e `scripts` depois da reorganização.

## Estado dos modelos

`z-image-turbo-fast`, `wan21-t2v-1.3b-fast`, `wan21-i2v-14b-first-frame` e `wan21-flf2v-14b-720p-q4` possuem manifestos de download, mas todos os pesos estão ausentes. Nenhuma imagem, vídeo ou malha gerada por rede neural foi produzida nesta validação.
