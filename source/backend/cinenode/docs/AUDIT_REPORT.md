# Auditoria real — Avangard Visual 0.2.0

Data: 2026-08-06

## Correção da entrega anterior

A versão 0.1 possuía código de API, banco, fila, editor e adapters, mas os testes aprovados não executavam modelo neural. A conclusão anterior misturou “controle funciona” com “IA gera”. Isso estava errado.

## O que foi refeito

- catálogo ampliado de 11 para 24 nós;
- portas tipadas e validação de multiplicidade;
- Diretor IA que cria e persiste um DAG;
- referências múltiplas com funções explícitas;
- start frame e end frame separados;
- profiles T2V, I2V e FLF2V;
- adapters Freepik, Replicate, fal.ai, Tripo v2 e REST genérico;
- 3D local/cloud;
- preflight obrigatório antes do job;
- diagnóstico real de provider;
- interface do agente/providers;
- governança atualizada com gates de inferência abertos.

## Taxonomia das provas

### Nível A — estrutura

Compilação/sintaxe, JSON, imports, banco, migrations, segurança e pacote.

### Nível B — protocolo

Requisições e respostas de providers com transportes simulados; linha de comando produzida para binaries falsos controlados; polling, cancelamento e materialização verificados.

### Nível C — execução não neural

FFmpeg real, SQLite real, HTTP real, navegador real e arquivos produzidos por ferramentas não neurais.

### Nível D — inferência neural

Modelo real + peso real + GPU/CPU real + output visual/3D real. **Nenhum gate Nível D foi executado neste ambiente.**

## Provas executadas

- `pytest -q`: 43 testes aprovados.
- Chromium: Diretor IA → DAG → pré-voo → providers → governança, sem erros de console ou rede.
- FFmpeg: resize real e transcodificação.
- preflight: grafo estruturalmente válido permanece bloqueado quando engine/peso/chave falta.
- provider contracts: Freepik first/last, Tripo multiview, erros de chave e polling.
- mesh adapter: job só conclui quando uma malha não vazia existe.

## O que ainda não funciona comprovadamente

1. inferência local de imagem;
2. inferência local de vídeo T2V/I2V/FLF2V;
3. inferência local 3D;
4. chamadas cloud com contas/chaves reais;
5. incorporação física do package Vibe Workflow na interface ativa;
6. build Tauri/Setup.exe assinado;
7. benchmark no Alienware 18.

## Resultado do gate

`SESSÃO IMPLEMENTADA, MAS REPROVADA NA AUDITORIA`

A reprovação é causada pelos gates Nível D e hardware-alvo ainda não executados. Não há declaração de que “a IA funciona” sem esses outputs.

## Validação do ZIP candidato

O pacote foi extraído com `unzip`, teve 171 hashes internos aprovados, 43 testes aprovados, smoke/validador aprovados, instalação do wheel aprovada, health HTTP 200 e E2E Chromium sem erros. Os gates neurais continuam abertos e o estado de governança continua `DEGRADED`.
