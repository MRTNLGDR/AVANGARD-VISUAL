# Validação no Alienware 18

Os comandos abaixo são gates; só marque como aprovados após preservar outputs e logs.

## 1. Núcleo

```powershell
pytest -q
python utilities\validate_package.py --root . --run-smoke
python utilities\browser_e2e.py --root . --screenshots assets\previews\v0.2.0-e2e
```

## 2. Instalar engines

```powershell
.\utilities\bootstrap-opensources.ps1
.\utilities\install-engines.ps1 -Core -WithLLM -WithOpenCode -WithComfyUI -With3D
```

## 3. Imagem local

Baixe o bundle recomendado, execute um nó `image.generate` e preserve PNG, log, perfil, seed, duração, pico de VRAM e SHA-256.

## 4. Vídeo

Execute separadamente:

- T2V com `wan21-t2v-1.3b-fast`;
- I2V com `wan21-i2v-14b-first-frame`;
- FLF2V com `wan21-flf2v-14b-720p-q4`, duas imagens distintas e confirmação visual do primeiro/último frame.

## 5. 3D

```powershell
.\utilities\install-3d-engines.ps1
```

Gere um GLB com trellis.cpp e uma malha com TripoSR. Valide tamanho > 0, leitura pelo Blender, número de vértices/faces, materiais/texturas e turntable.

## 6. Cloud

Para cada provider habilitado, use **Providers → Executar chamada real**. Preserve ID remoto, status, resposta sem segredos, output local e hash. Repita com cancelamento e erro de parâmetro.

## 7. Instalação Windows

```powershell
.\utilities\build-tauri.ps1 -Clean
```

Teste em pasta/usuário limpos, iniciar/parar/reiniciar, backup/restore, atualização, desinstalação e SmartScreen/assinatura.
