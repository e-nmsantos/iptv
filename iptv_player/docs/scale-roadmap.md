# Escala e arquitetura

Estado da fundação em 11 de agosto de 2026.

Atualização de 12 de agosto de 2026: leitura paginada Room/Flow ativada em
produção, esquema Android v6 com EPG persistente, página inicial/favoritos,
guia agora/a seguir, testes de navegação D-pad, métricas locais do player e
sincronização local nos dois sentidos sem URLs ou credenciais. As escritas de
catálogo continuam temporariamente no importador SQLite diferencial, com
notificação explícita ao `InvalidationTracker`; a migração integral das escritas
para DAO Room permanece trabalho de consolidação.

## Entregue

- contrato comum `Provider` e adaptadores Xtream/Stalker;
- controlador de catálogo fora da janela Qt;
- repositórios separados para leituras de playlists e catálogo;
- migrações SQLite desktop explícitas e numeradas, atualmente v6;
- FTS5 desktop sincronizado por triggers;
- cliente HTTP comum com retries, timeouts e cancelamento cooperativo;
- Android SQLite v6 com FTS5, hashes de conteúdo, EPG persistente e atualização diferencial;
- Android abre apenas o cabeçalho e páginas de 240 itens, sem carregar o catálogo completo;
- importador M3U Android incremental, com leitura por stream, lotes de 500 itens,
  rollback transacional, cancelamento cooperativo e limite descomprimido de 256 MB;
- entidades, DAO paginado e adaptador `Flow<CatalogPage>` Room ativos em produção
  sobre o esquema v6; as escritas continuam no importador SQLite diferencial;
- filtros Android executados na base de dados e carregamento adicional por D-pad;
- diálogos Android extraídos de `IptvTvApp.kt` e pairing com ciclo de vida próprio;
- controladores desktop de playlists, catálogo, EPG, reprodução e tarefas separados
  de `MainWindow`;
- CI Windows/Linux/Android, cobertura mínima, APK e benchmark agendado de 100 mil itens;
- limite de tentativas de PIN e comparação criptográfica em tempo constante.

## Próximas entregas da fundação

- validar em dispositivo/emulador a atualização de todos os esquemas históricos;
- migrar as escritas incrementais do `SQLiteOpenHelper` para transações Room;
- dividir `CatalogViewModel` em catálogo, EPG, player e sincronização;
- ampliar os testes instrumentados de migração Android; os testes unitários de
  navegação D-pad já fazem parte da suite;
- limites automáticos para tempo, memória e tamanho dos lotes.

As fases de player comercial, EPG completo, sincronização bidirecional e releases
assinadas dependem desta fundação e permanecem planeadas; não devem ser tratadas
como concluídas apenas por existirem versões iniciais dessas funcionalidades.
