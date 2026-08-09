# Matriz de modelos e capacidades

| ID/perfil | Função | Local/cloud | Referências | Estado nesta auditoria |
|---|---|---|---|---|
| `z-image-turbo-fast` | texto→imagem | local sd.cpp | texto | adapter pronto; peso não executado |
| `flux-fast-quantized` | texto/img→imagem | local sd.cpp | uma imagem | adapter pronto; peso não executado |
| `wan21-t2v-1.3b-fast` | texto→vídeo | local sd.cpp | texto | adapter pronto; peso não executado |
| `wan21-i2v-14b-first-frame` | imagem→vídeo | local sd.cpp | start image | adapter/manifest prontos; não executado |
| `wan21-flf2v-14b-720p-q4` | first/last→vídeo | local sd.cpp | start + end | `--end-img` validado por contrato; não inferido |
| ComfyUI workflow | imagem/vídeo/3D | local sidecar | múltiplas | API implementada; workflows/pesos externos |
| WanGP | vídeo premium | local sidecar | conforme modelo | externo/licença própria; não executado |
| trellis.cpp | imagem→GLB | local | uma imagem | adapter/installer prontos; não executado |
| TripoSR | imagem→malha | local | uma ou mais imagens | adapter/installer prontos; não executado |
| Freepik | imagem/vídeo | cloud | start/end e refs conforme endpoint | contrato testado; sem chave real |
| Replicate | modelo arbitrário | cloud | conforme modelo | contrato testado; sem chave real |
| fal.ai | modelo arbitrário | cloud | conforme modelo | contrato testado; sem chave real |
| Tripo v2 | texto/imagem/multiview→3D | cloud | front/left/back/right | contrato testado; sem chave real |

## 4K/8K

4K/8K é um pipeline de entrega, não uma promessa de geração neural nativa em 8K: geração na resolução estável do modelo → upscale em tiles → interpolação quando vídeo → resize/crop → codec final. O preflight verifica cada etapa.
