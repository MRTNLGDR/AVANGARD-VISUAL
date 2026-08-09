# Modelos

Este diretório guarda o catálogo e o gerenciador de downloads. Pesos nunca são versionados no GitHub; por padrão ficam em `data/models`.

Hardware detectado nesta estação: NVIDIA GeForce RTX 4090 Laptop GPU, 16 GB de VRAM.

## Faixas recomendadas

- Rápido: `z-image-turbo-fast` para imagem e `wan21-t2v-1.3b-fast` para vídeo 480p.
- Qualidade: FLUX.1 Schnell quantizado para imagem; Wan 14B quantizado com offload para I2V e first/last-frame.
- 3D viável: Hunyuan3D 2 Mini em modo low-VRAM, depois que o adapter Windows for implementado e validado.
- Não indicado nesta GPU: TRELLIS.2 oficial, que declara no mínimo 24 GB de VRAM.

## Comandos

```powershell
python .\models\manager.py list
python .\models\manager.py verify all
.\utilities\download-models.ps1 -Bundle recommended
```

`catalog.json` distingue `integrated`, `candidate` e `blocked`. Um item candidato não aparece como engine pronta no aplicativo.
