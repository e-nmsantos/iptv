# Registo de alterações (IPTV Player TV)

Histórico de mudanças relevantes da aplicação Android TV. O `README.md`
descreve apenas o estado atual.

## 0.14.0-beta01

- Descodificadores FFmpeg incluídos (AC-3, E-AC-3, DTS, TrueHD, MP2…): acaba o
  "imagem sem som" em boxes sem esses codecs. Hardware primeiro, FFmpeg como
  recurso; opção "Preferir FFmpeg" nas Definições. Passthrough HDMI automático.
- Suporte DASH.
- Pausa em direto (timeshift em memória, 64–256 MB) com indicação "EM DIFERIDO"
  e botão "Ir para o direto"; ⏩/⏪ avançam e recuam em canais HLS com janela.
- Banner "agora / a seguir" com logótipo, número, progresso e descrição em cada
  zapping (também com INFO).
- Zapping por número (0–9), canal anterior (botão verde ou ⟲) e painel de
  opções do direto com ▶ (áudio, legendas, estatísticas, favorito).
- Estatísticas da stream: resolução, fps, codecs, descodificador
  (hardware/FFmpeg), débito, buffer e frames perdidos (botão azul).
- Novo Início com destaque, "Continuar a ver" (com progresso e próximo
  episódio), vistos recentemente, favoritos, filmes e séries adicionados
  recentemente.
- Próximo episódio: cartão nos últimos 20 s e reprodução automática após 10 s
  (configurável); funciona também ao retomar a partir do Início.
- Progresso guardado a cada 30 s; episódios com identificador estável (antes,
  "S01 E01" de séries diferentes partilhavam o ponto de retoma).
- Lembretes no Guia TV: OK num programa futuro cria um lembrete 🔔 que avisa
  um minuto antes, por cima do catálogo ou do player.
- Ecrã de Definições: descodificação, pausa em direto, estatísticas, próximo
  episódio automático e abrir no último canal.

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
