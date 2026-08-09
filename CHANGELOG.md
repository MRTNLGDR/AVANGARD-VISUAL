# Changelog

## 0.3.0 - 2026-08-09

### Changed

- Produto e shell renomeados integralmente para Avangard Visual.
- Dashboard reconstruído como centro de produção para imagem, filme e 3D.
- Código principal, assets, modelos, utilidades, vendor e material histórico separados.
- Catálogo de modelos alinhado à RTX 4090 Laptop de 16 GB, sem promover candidatos a engines prontas.
- Token antigo da CLI do GitHub removido; publicação passa pela conexão oficial do repositório.

## 0.2.0 — 2026-08-06

### Added
- Diretor IA com regras determinísticas e planejamento opcional por Ollama.
- 24 nós com portas tipadas, multiplicidade e validação de ciclo.
- Referências múltiplas com papéis semânticos.
- Start/end frame real para FLF2V e contrato cloud `image_tail`.
- Providers Freepik, Replicate, fal.ai, Tripo v2 e REST genérico.
- 3D por trellis.cpp, TripoSR, Tripo cloud, ComfyUI e CLI configurável.
- Pré-voo de binários, pesos, workflows, chaves, endpoints e assets.
- Tela de providers, diagnóstico real e registro de resultados.
- Instaladores opcionais de ComfyUI e engines 3D.
- Testes de contratos, agente, DAG, pré-voo, 3D e E2E do Diretor IA.

### Fixed
- O agente de edição agora conecta a imagem-base à porta correta.
- Máscara sem imagem-base é rejeitada.
- Start/end não é convertido silenciosamente em multirreferência.
- Parser Freepik reconhece outputs em `generated[]`.
- A suíte roda com `pytest` direto via `pytest.ini`.
- A interface testada é a mesma interface servida pelo backend.

### Audit correction
- A 0.1 não executou inferência neural apesar de ter aprovado testes de controle. Essa distinção agora é explícita e os gates de inferência permanecem abertos.
