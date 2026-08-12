# 📺 IPTV Player

Um player de IPTV moderno e completo feito em Python com PySide6 e VLC.

## ✨ Funcionalidades

### Formatos Suportados
- **M3U / M3U8 / M3U_Plus** — Playlists com tags EXTINF, grupos, logos, EPG
- **Xtream Codes API** — API JSON com canais ao vivo, séries, VOD e EPG
- **Stalker Portal (MAC)** — Portal Middleware Stalker com autenticação MAC
- **EPG XMLTV** — Guia de programação eletrónico

### Funcionalidades Principais
- 🎨 Interface moderna com tema escuro
- ▶ Reprodução de streams com VLC (aceleração por hardware)
- 📋 Gestão de múltiplas playlists
- 🔍 Pesquisa de canais com filtro por grupos
- 🌍 Canais Stalker organizados por região e categoria original do portal
- ⭐ Favoritos
- 📅 Guia EPG com programa atual em destaque
- 🔄 Cache e atualização automática de EPG XMLTV/XMLTV.GZ
- 🔐 Credenciais e URLs sensíveis cifrados na base de dados
- 🔗 Importar de URL ou ficheiro local
- 🔄 Carregamento assíncrono (UI não bloqueia)
- ⚙ Definições configuráveis

## 📋 Requisitos

- Python 3.9+
- [VLC media player](https://www.videolan.org/vlc/) instalado no sistema

## 🚀 Instalação

1. **Clonar o repositório** (ou descarregar os ficheiros)
2. **Instalar dependências:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Instalar o VLC** (se não tiver):
   - Descarrega de: https://www.videolan.org/vlc/
   - Ou instala via chocolatey: `choco install vlc`

4. **Executar:**
   ```bash
   python main.py
   ```

## Testes locais

Os testes de regressão não fazem pedidos a serviços externos:

```bash
python -m unittest discover -s tests -v
```

Para executar também as verificações usadas pela integração contínua:

```bash
pip install -r requirements-dev.txt
python -m pytest
python -m ruff check src tests
python -m compileall -q main.py config src tests
```

Os ficheiros `test_*.py` na raiz são ferramentas manuais de diagnóstico de
rede. Para os usar, define primeiro `IPTV_TEST_PORTAL` e `IPTV_TEST_MAC`.
Sem estas variáveis, usam apenas um endereço local seguro.

## Armazenamento seguro

Palavras-passe, utilizadores, MAC, URLs de streams e cabeçalhos de autenticação
são cifrados com AES-GCM antes de entrarem na base de dados. A chave é guardada
no gestor de credenciais do sistema através de `keyring`.

Bases de dados de versões anteriores são migradas automaticamente no primeiro
arranque. Não removas a entrada `IPTV Player / database-encryption-key-v1` do
gestor de credenciais: sem essa chave, os dados cifrados não podem ser
recuperados.

## EPG automático

Playlists M3U que indiquem `x-tvg-url` ou `url-tvg` carregam XMLTV local, remoto
ou comprimido com gzip. A cache é apresentada imediatamente e atualizada
segundo o intervalo configurado. Em playlists Xtream e Stalker, o EPG é
carregado quando um canal é selecionado. A opção **Ficheiro → Atualizar EPG**
força uma atualização XMLTV.

## Catálogos grandes

Playlists Xtream e Stalker importam primeiro os canais Live. VOD e séries são
carregados em segundo plano quando o respetivo separador é aberto pela primeira
vez e ficam em cache local.

Usa **F6** ou **Playlists → Atualizar catálogo atual** para atualizar o
separador aberto. A atualização é transacional e preserva favoritos através dos
identificadores estáveis do fornecedor. O progresso por categoria aparece na
barra de estado.

As fontes M3U/EPG têm limites de segurança: 100 MB para a origem e 256 MB para
XMLTV descomprimido.

## 🎯 Como Usar

### Importar Playlist M3U
1. Clica em "📺 Importar M3U / M3U8"
2. Escolhe ficheiro local ou insere URL
3. Dá um nome à playlist
4. Clica "Importar"

### Xtream Codes
1. Clica em "🔗 Xtream Codes API"
2. Insere URL do servidor, username e password
3. Clica "Ligar"

### Stalker Portal
1. Clica em "📡 Stalker Portal (MAC)"
2. Insere URL do portal e endereço MAC
3. Clica "Ligar"

### Reproduzir Canal
- Duplo clique num canal da lista
- Ou seleciona e clica no botão play

## 📁 Estrutura do Projeto

```
iptv_player/
├── main.py                     # Ponto de entrada
├── requirements.txt            # Dependências
├── README.md                   # Documentação
├── config/
│   ├── __init__.py
│   └── settings.py             # Gestão de definições
├── src/
│   ├── core/
│   │   ├── channel.py          # Modelo de canal
│   │   ├── playlist.py         # Modelo de playlist
│   │   ├── epg.py              # Dados EPG
│   │   └── database.py         # Base de dados SQLite
│   ├── parsers/
│   │   ├── m3u_parser.py       # Parser M3U/M3U8/M3U_Plus
│   │   ├── xtream_parser.py    # Cliente Xtream Codes API
│   │   └── stalker_parser.py   # Cliente Stalker Portal
│   ├── player/
│   │   └── media_player.py     # Player VLC
│   ├── ui/
│   │   ├── main_window.py      # Janela principal
│   │   ├── playlist_widget.py  # Gestão de playlists
│   │   ├── channel_list.py     # Lista de canais
│   │   ├── player_widget.py    # Controlos do player
│   │   ├── epg_widget.py       # Guia EPG
│   │   └── dialogs.py          # Diálogos
│   └── utils/
│       ├── helpers.py          # Funções auxiliares
│       └── logger.py           # Sistema de logging
└── resources/
    └── icons/                  # Ícones
```

## 🛠 Tecnologias

- **PySide6** — Interface gráfica Qt6
- **python-vlc** — Reprodução de streams
- **requests / aiohttp** — Clientes HTTP
- **lxml** — Parsing XML (EPG XMLTV)
- **SQLite** — Base de dados local

## 📝 Notas

- O VLC tem de estar instalado para a reprodução funcionar
- Alguns streams podem precisar de User-Agent específico (configurável nas definições)
- Os dados são guardados em `%APPDATA%/iptv-player/` (Windows) ou `~/.config/iptv-player/` (Linux/macOS)

## 🍎 Build para macOS

Ver [`packaging/macos/README.md`](packaging/macos/README.md) para gerar um `.app`/`.dmg` distribuível (build tem de correr num Mac).

## Desempenho e catálogos extensos

As listas apresentam no máximo 250 itens de cada vez, com navegação entre
páginas. A pesquisa abrange o catálogo completo e nomes de categorias, com um
pequeno atraso controlado para manter a interface fluida. Operações longas
mostram progresso e um botão **Cancelar** na barra de estado.

O separador **Info** mostra os últimos itens reproduzidos na playlist atual. O
histórico guarda apenas o nome, tipo e data; nunca duplica URLs de stream.

Na versão 0.4, `Ctrl+K` abre uma pesquisa global em todas as playlists. Clique
simples apenas seleciona; duplo clique ou Enter reproduz. Filmes e episódios
retomam automaticamente a partir do último ponto guardado, e os controlos do
player permitem escolher áudio, legendas internas ou um ficheiro externo.

O menu de contexto das playlists permite editar e testar uma ligação antes de
a guardar. O menu **Ficheiro** exporta e importa backups portáteis cifrados por
palavra-passe sem apagar dados existentes. Cada canal tem ainda um diagnóstico
de disponibilidade que mostra servidor, protocolo, estado HTTP e latência sem
revelar URLs ou credenciais.

Em fontes M3U, Live, VOD e Séries são separados através dos metadados, das
categorias e dos caminhos `/live/`, `/movie/` e `/series/`. Playlists guardadas
por versões anteriores são corrigidas automaticamente quando forem abertas.

Para medir regressões sem dados nem credenciais reais:

```bash
python -m benchmarks.catalog_benchmark --sizes 10000 50000 100000
```

O benchmark usa uma base temporária e mede gravação cifrada, paginação,
pesquisa, contagem e memória de pico.

## Build para Windows

Ver [`packaging/windows/README.md`](packaging/windows/README.md). O build cria
uma distribuição PyInstaller e executa os testes antes de empacotar. O processo
de release também cria um ZIP portátil, checksums SHA-256, manifesto de
atualização e um instalador Inno Setup quando o compilador está disponível.

## Utilização responsável

Esta aplicação é um leitor: não fornece listas, contas ou conteúdos. Usa apenas
fontes para as quais tenhas autorização e respeita os direitos e condições do
fornecedor. Não existe funcionalidade destinada a contornar autenticação ou
restrições de acesso.
