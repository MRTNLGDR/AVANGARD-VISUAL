# Integração open source

## Política

Todos os upstreams são pinados em `vendor/opensources/manifest.json`. O original é clonado com submódulos para quarentena, auditado e promovido sem alterações para `upstream/`. Integrações e builds ficam fora do backup original.

## Repositórios fornecidos pelo usuário

### OpenCode

Agente de código. É chamado como ferramenta local para diagnóstico/reparo de workflow; não é uma engine de imagem/vídeo.

### Vibe Workflow

Fornece uma implementação React Flow de editor visual e componentes de mídia/API. Foi usado como referência de comportamento e schema. O runtime 0.2 servido pelo backend é um canvas tipado próprio. O clone/package não está fisicamente embutido; `VIBE-EMBED-001` permanece pendente.

### Open Generative AI

É catálogo e coleção de integrações/exemplos. Não constitui sozinho uma engine local. As ideias compatíveis foram traduzidas para o registro de providers do CineNode.

## Engines adicionais necessárias

- stable-diffusion.cpp: image/video local e suporte FLF2V.
- ComfyUI: sidecar de workflows complexos/multirreferência.
- Real-ESRGAN NCNN: upscale.
- RIFE NCNN: interpolação.
- FFmpeg: composição/exportação.
- Ollama: LLM/VLM local.
- trellis.cpp e TripoSR: geração 3D local.
- Tripo API: 3D cloud.

## Licenças não permissivas

ComfyUI permanece sidecar GPL não redistribuído. WanGP permanece externo e exige aceite explícito da licença comunitária. Nenhuma dessas bases é copiada silenciosamente para o produto MIT.
