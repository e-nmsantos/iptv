# IPTV Player TV

Cliente Android TV nativo do IPTV Player. Este projeto é independente da
aplicação desktop e usa Kotlin, Compose for TV e AndroidX Media3.

O histórico de versões está no ficheiro [`CHANGELOG.md`](CHANGELOG.md).

## MVP atual

- importação M3U/M3U8 por URL HTTP(S) ou ficheiro;
- envio de uma lista pelo telemóvel através de QR code e página local temporária;
- ligações M3U, Xtream Codes e Stalker Portal (MAC), na TV ou pelo QR;
- separação automática entre Em direto, Filmes e Séries;
- grupos e pesquisa do catálogo;
- navegação por D-pad, sem depender de toque;
- reprodução através de Media3 ExoPlayer, incluindo cabeçalhos User-Agent e Referer;
- catálogo persistente em SQLite;
- biblioteca com várias listas guardadas, seleção instantânea, atualização e remoção;
- URLs e cabeçalhos cifrados através do Android Keystore;
- limite de 100 MB no download e 256 MB após descompressão;
- launcher próprio para Android TV;
- navegação lateral própria para comando, com Live, Filmes, Séries e pesquisa;
- canais compactos e posters dedicados para VOD/Séries;
- logos e capas remotas com cache local;
- diagnóstico e repetição quando um stream falha no player;
- guia lateral dentro do player, vídeo e canais lado a lado, com zapping por comando;
- EPG XMLTV incremental com o programa atual apresentado no catálogo;
- favoritos persistentes (botão vermelho do comando durante a reprodução);
- retoma automática de filmes e episódios;
- sincronização de favoritos e retoma a partir da aplicação desktop, sem copiar URLs ou credenciais;

As listas ficam em cache na televisão. Trocar de lista em **Listas** abre o
catálogo local sem voltar a contactar o servidor; **Atualizar** é a ação que
descarrega a versão mais recente. As consultas independentes de Xtream Codes
são executadas em paralelo e a chave do Android Keystore é reutilizada durante
a sessão para acelerar catálogos grandes.

No player, **OK**, seta esquerda, `Guide` ou `Menu` abre a lista lateral. A seta
direita ou `Back` fecha-a; com o guia fechado, cima/baixo e Channel+/Channel−
mudam diretamente de canal. Um segundo `Back` regressa ao catálogo.

O guia do player separa **categorias**, **canais da categoria** e **vídeo**. Da
lista de canais, esquerda entra nas categorias e direita regressa ao ecrã
inteiro; em ecrã inteiro, esquerda reabre diretamente o guia no canal atual.
O vídeo mantém uma única superfície `TextureView` estável enquanto o guia é
aberto ou fechado, evitando congelamentos do descodificador em algumas TVs.
O player de TV em direto monitoriza fim prematuro, buffering prolongado e
refaz a ligação automaticamente e renova a sessão Stalker quando necessário.
Usa ligações persistentes, timeout de leitura próprio para IPTV, repetição live
e retentativas internas do Media3 sem reinícios baseados em timestamps. A última categoria selecionada e a sua posição são mantidas
ao fechar e reabrir o guia.

## Enviar pelo telemóvel

Na televisão escolhe **Adicionar lista → Enviar pelo telemóvel (QR)**. Lê o
código com a câmara de um telemóvel ligado à mesma rede e escolhe uma das
ligações disponíveis: M3U/M3U8, Xtream Codes ou Stalker Portal. O
emparelhamento:

- funciona apenas na rede local e não usa serviços externos;
- usa um endereço aleatório de utilização única;
- expira após cinco minutos;
- limita o tamanho dos pedidos recebidos;
- nunca escreve o endereço recebido nos logs.

Como a página local usa HTTP, esta opção deve ser usada apenas numa rede
doméstica de confiança. As URLs continuam cifradas pelo Android Keystore quando
são guardadas na televisão.

## Sincronizar com o computador

Na aplicação desktop seleciona a mesma playlist e escolhe **Playlists → Copiar
favoritos e retoma para a TV**. Depois abre o QR code da TV no navegador, cola
o conteúdo na secção **Sincronização do computador** e confirma. O payload usa
identificadores SHA-256 estáveis e contém apenas favoritos e tempos de retoma;
URLs, utilizadores, passwords e endereços MAC não são incluídos.

O nome da lista é obtido automaticamente do URL ou ficheiro. Abrir ou executar
uma lista nunca mostra uma janela para mudar o nome.

## Compilar

Abre a pasta `android-tv` no Android Studio e executa a configuração `app` num
emulador Android TV ou num dispositivo real. Pela linha de comandos:

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$env:PATH = $env:PATH.Replace('"', '')
./gradlew.bat testDebugUnitTest assembleDebug
```

O APK de desenvolvimento é criado em
`app/build/outputs/apk/debug/app-debug.apk`.

## Próximas integrações

Xtream carrega canais, filmes e séries; os episódios são obtidos apenas quando
a série é aberta. Stalker autentica por MAC, carrega os catálogos disponíveis e
resolve links temporários no momento da reprodução. O player envia também
cookie MAC, token Bearer, Referer e identificação MAG quando o portal os exige.
O EPG XMLTV é carregado em background e retém apenas o programa que está no ar,
evitando manter a árvore XML completa em memória.

Usa exclusivamente listas e conteúdos para os quais tenhas autorização.
