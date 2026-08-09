# Backup, restauração e recuperação

## Banco e jobs

SQLite usa WAL, foreign keys, busy timeout e migrations transacionais. No startup:

- job abandonado em `RUNNING` vira `FAILED` com `PROCESS_INTERRUPTED`;
- job ainda `QUEUED` permanece elegível e é retomado pela fila;
- nenhum job interrompido é apresentado como sucesso.

## Backup

```bash
python -m cinenode backup
```

O backup usa a API SQLite, inclui manifesto e SHA-256 e pode incluir assets/outputs. A UI lista pacotes disponíveis.

## Restore validado

1. valida paths do ZIP contra traversal;
2. extrai em diretório temporário;
3. valida manifesto/checksum;
4. executa `PRAGMA integrity_check` no banco candidato;
5. cria safety backup do banco atual;
6. fecha conexão;
7. substitui o banco atomicamente;
8. remove `-wal` e `-shm` antigos;
9. reabre/migra e valida novamente.

O teste de regressão confirmou backup → alteração → restore e rejeição de ZIP malicioso.

## Recuperação manual

1. pare o aplicativo;
2. copie `data/` para armazenamento seguro;
3. execute integridade no SQLite;
4. restaure o pacote mais recente;
5. inicie e execute `cinenode doctor`;
6. reenvie somente jobs falhos após conferir inputs e espaço livre.

Modelos/engines são reproduzíveis; banco e mídia do usuário são o escopo crítico de backup.
