# QUICKSTART

## WINDOWS

1. Extraia o ZIP.
2. Abra PowerShell na pasta extraída.
3. Execute `PowerShell -ExecutionPolicy Bypass -File .\install.ps1 -SkipOpenSources`.
4. Execute `run.bat`.
5. Abra `http://127.0.0.1:8787`.

Para inferência local, sincronize os upstreams e instale engines/pesos:

```powershell
.\utilities\bootstrap-opensources.ps1
.\utilities\install-engines.ps1 -Core -WithLLM -WithOpenCode -WithComfyUI -With3D
.\utilities\download-models.ps1 -Bundle recommended
```

## MACOS

```bash
./install.command
./run.command
```

O shell Tauri/DMG ainda precisa ser compilado e validado em macOS.

## LINUX

```bash
chmod +x install.sh run.sh stop.sh uninstall.sh
./install.sh --skip-opensources
./run.sh
```

## PRIMEIRO WORKFLOW

1. Importe arquivos em **Galeria** ou no **Diretor IA**.
2. Abra **Diretor IA**.
3. Selecione o resultado: imagem, vídeo, filme ou 3D.
4. Marque cada referência e escolha sua função.
5. Para vídeo entre dois quadros, marque exatamente uma imagem como `start_frame` e outra como `end_frame`.
6. Clique **Criar workflow executável**.
7. No editor, clique **Pré-voo real**.
8. Só execute quando todos os bloqueios obrigatórios estiverem resolvidos.

## CLOUD

Preencha as chaves em `.env`, habilite o provider nas configurações e use **Providers → Executar chamada real**. Não grave a chave dentro do JSON da interface.
