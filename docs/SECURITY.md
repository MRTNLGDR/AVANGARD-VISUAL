# Segurança

## Fronteira local

O servidor usa `127.0.0.1` por padrão. Middleware valida `Host`, origem, `Sec-Fetch-Site`, cliente loopback e token quando fornecido. Isso reduz DNS rebinding e chamadas cross-site. Docker publica somente no loopback e habilita proxy loopback explicitamente.

## Supply chain

- Upstreams são pinados por commit e clonados em quarentena.
- O scanner rejeita Unicode invisível/bidirecional crítico antes de instalar dependências.
- Scripts de lifecycle e binários rastreados entram no relatório para revisão.
- Arquivos rastreados recebem SHA-256 e licenças são preservadas.
- WanGP exige aceite explícito; ComfyUI/WanGP não são incorporados silenciosamente.
- Nenhum script de upstream é executado durante a etapa de auditoria.

A varredura reduz uma classe de risco, mas não prova ausência de malware. Para produção, executar também antivírus, SBOM/SCA, revisão de diffs, sandbox/VM e assinatura interna dos artefatos aprovados.

## Arquivos

- Nomes enviados são reduzidos a basename seguro.
- Tamanho é limitado durante streaming.
- Caminhos de assets/restore precisam permanecer nas raízes permitidas.
- Restore rejeita ZIP traversal, valida manifesto, SHA-256 e `PRAGMA integrity_check`.
- Troca de banco é atômica; WAL/SHM antigos são removidos para impedir replay de estado anterior.

## Processos

- Engines executam com lista de argumentos e `shell=False`.
- Executáveis/modelos/inputs são validados antes do launch.
- Timeout e cancelamento encerram subprocessos.
- Erros e tails de stdout/stderr permanecem auditáveis.

## Segredos

O token local é gerado em `data/.local-token`, com permissão restrita quando suportada. `HF_TOKEN` é usado somente pelo downloader e não entra no banco/repositório. O núcleo não exige chave paga.

## Gaps de produção ainda abertos

- Assinar instaladores Windows/macOS.
- Executar SCA/CVE no ambiente exato do build com rede.
- Auditar e materializar todos os upstreams no Alienware.
- Aplicar ACLs de pasta em máquinas multiusuário.
- Executar benchmark/soak test CUDA com monitoramento térmico.
