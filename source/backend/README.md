# Avangard Visual 0.3.0

Gerenciador nodal local-first para criação de imagens, vídeos, filmes e malhas 3D. Esta versão substitui o núcleo anterior que validava apenas banco/API por um DAG tipado, um Diretor IA, adapters reais, pré-voo de dependências e uma separação explícita entre **teste de protocolo** e **inferência neural real**.

## Estado honesto desta entrega

O aplicativo, banco, editor, agente, fila, providers, pré-voo, pós-processamento e governança funcionam neste pacote. Os modelos neurais não estão embutidos. Neste executor não existiam NVIDIA GPU, pesos multi-GB ou chaves cloud; portanto nenhuma geração neural de imagem, vídeo ou 3D foi classificada como aprovada. O aplicativo bloqueia a execução e mostra exatamente o binário, peso, workflow, chave ou endpoint ausente.

## Fluxos implementados

- Diretor IA por brief, com planejador determinístico ou Ollama local em JSON validado.
- Imagem por texto; edição/img2img; máscara; referências de personagem, estilo, produto, composição e ambiente.
- Vídeo T2V, I2V, multirreferência e first/last-frame, com portas distintas `start_frame` e `end_frame`.
- Filme com múltiplos takes, concatenação, resize, interpolação, upscale e exportação.
- 3D por imagem única ou multiview, com papéis `front`, `left`, `back`, `right`, `top` e `bottom`.
- Providers locais: stable-diffusion.cpp, ComfyUI, WanGP externo, Ollama, trellis.cpp, TripoSR, CLI 3D genérico, Real-ESRGAN, RIFE, FFmpeg e Blender.
- Providers cloud: Freepik, Replicate, fal.ai, Tripo API v2 e REST genérico configurável.
- SQLite, fila persistente, cancelamento, retry, recuperação, backup/restauração e galeria local.
- Governança única em `/api/governance/snapshot`, polling de 15 s, refetch no foco, SSE e menu próprio.

## Catálogo de nós

A versão 0.2 possui 24 tipos de nó: entrada de texto, asset e referências; Diretor IA; LLM/VLM; composição de prompt; geração/edição/upscale/resize de imagem; geração T2V/I2V, first-last, vídeo por referências, extração, concatenação, resize, interpolação e upscale; geração/preview/exportação 3D; exportação e preview de mídia.

As portas são tipadas. Conexões incompatíveis, ciclos, entradas obrigatórias ausentes, multiplicidade inválida e assets inexistentes são rejeitados antes da fila.

## Instalação do núcleo

### Windows

```powershell
PowerShell -ExecutionPolicy Bypass -File .\install.ps1 -SkipOpenSources
.\run.bat
```

### Linux/macOS

```bash
./install.sh --skip-opensources
./run.sh
```

Interface: `http://127.0.0.1:8787`.

## Sincronização open source controlada

```powershell
.\utilities\bootstrap-opensources.ps1
```

ou:

```bash
./utilities/bootstrap-opensources.sh
```

O processo clona commits pinados em quarentena, inicializa submódulos, procura Unicode invisível/bidirecional, gera hashes e só então promove o clone para `vendor/opensources/upstream/`.

## Engines locais

```powershell
.\utilities\install-engines.ps1 -Core -WithLLM -WithOpenCode -WithComfyUI -With3D
.\utilities\download-models.ps1 -Bundle recommended
```

```bash
./utilities/install-engines.sh --with-llm --with-opencode --with-comfyui --with-3d
./utilities/download-models.sh recommended
```

Bundles específicos de vídeo:

```text
wan21-i2v-14b-first-frame
wan21-flf2v-14b-720p-q4
```

A instalação das engines e o download de pesos não foram executados neste ambiente. Os scripts existem, têm sintaxe validada e falham de forma explícita; ainda precisam do gate no Alienware.

## Cloud opcional

Copie `.env.example` para `.env` e preencha somente os providers usados:

```text
FREEPIK_API_KEY=
REPLICATE_API_TOKEN=
FAL_KEY=
TRIPO_API_KEY=
GENERIC_PROVIDER_API_KEY=
```

Depois habilite o provider em **Configurações → Providers cloud**. O botão **Executar chamada real** não é um teste cosmético: ele cria a tarefa no provider, acompanha o status e materializa o output no armazenamento local, ou retorna o erro real.

## 3D

- `trellis.cpp`: imagem → GLB texturizado; binário nativo, pesos separados.
- `TripoSR`: imagem única → OBJ/malha; Blender pode converter para GLB.
- `cloud.tripo`: texto, imagem ou multiview pela API v2.
- `local.comfyui`: workflows 3D multiview fornecidos como API JSON.
- `local.generic_3d_cli`: comando explícito com placeholders e validação de arquivo final.

Nenhum nó 3D gera arquivo fictício. O job só conclui quando uma malha não vazia existe.

## Vibe Workflow e OpenCode

Vibe Workflow foi auditado como referência React Flow. **O runtime ativo da 0.2 é um canvas tipado próprio e o package do Vibe ainda não está fisicamente incorporado**, porque o clone não pôde ser materializado neste executor. Essa pendência está aberta na governança como `VIBE-EMBED-001`.

OpenCode é integrado como agente local de código/reparo, não como modelo de imagem ou vídeo. O Diretor IA de mídia pertence ao CineNode e usa Ollama quando disponível.

## Testes

```bash
pytest -q
python utilities/browser_e2e.py --root . --screenshots assets/previews/v0.2.0-e2e
python utilities/validate_package.py --root . --run-smoke
```

Resultado local da versão 0.3: **40 testes aprovados, 3 contratos POSIX ignorados no Windows**, API HTTP 200 e dashboard no navegador interno com 0 erros de console. A inferência neural continua bloqueada até os pesos serem instalados e testados.
