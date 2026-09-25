# Registo de alterações (IPTV Player TV)

Histórico de mudanças relevantes da aplicação Android TV. O `README.md`
descreve apenas o estado atual.

## 0.13.0-beta01

- Listas M3U lidas progressivamente e persistidas em lotes de 500 itens.
- Atualizações comparam hashes de conteúdo, mantêm IDs e favoritos, não
  voltam a cifrar linhas inalteradas e removem apenas conteúdos que deixaram
  de existir.
- DAO Room paginado e respetivo adaptador Flow para as leituras de produção
  sobre o esquema SQLite v6.
- Escritas incrementais no importador SQLite diferencial que notificam
  explicitamente o Room.

## 0.12

- `Listas` e `Adicionar` passam a ser áreas completas da aplicação, em vez de
  janelas sobre o catálogo.
- Arranque lê primeiro o índice das listas e os metadados dos conteúdos; URLs
  e cabeçalhos protegidos só são decifrados ao abrir um canal, filme ou série.
- Operações SQLite serializadas para evitar conflitos `database is locked`
  durante importações e atualizações.

## 0.6

- Navegação lateral própria para comando, com Live, Filmes, Séries e pesquisa.
- Guia lateral dentro do player, vídeo e canais lado a lado, com zapping por
  comando.
- EPG XMLTV incremental, retendo apenas o programa atualmente no ar.
