# Build para Windows

Executa em PowerShell, a partir de qualquer diretório:

```powershell
.\packaging\windows\build.ps1
```

O resultado fica em `dist\IPTVPlayer`. O VLC não é redistribuído: deve estar
instalado no sistema de destino ou ser selecionado nas definições da aplicação.

Para distribuição pública ainda é necessário assinar o executável/instalador
com um certificado de code signing e produzir um instalador (por exemplo MSI).

## Release completa

O comando seguinte produz o ZIP portátil, `SHA256SUMS.txt`, o manifesto de
atualização e, quando o Inno Setup está instalado, o instalador `.exe`:

```powershell
.\packaging\windows\release.ps1
```

Para instalar o compilador do instalador localmente:

```powershell
choco install innosetup
```

Os resultados ficam em `release\`. A workflow `Windows release` executa o
mesmo processo para tags `v*` ou manualmente e adiciona proveniência Sigstore
em repositórios públicos. A assinatura Authenticode continua a exigir um
certificado privado de code signing.
