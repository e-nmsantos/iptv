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

## Assinatura do manifesto de atualizações

O manifesto é validado com SHA-256 do artefacto e, opcionalmente, com uma
assinatura **Ed25519** verificada pela aplicação. Para ativar a verificação:

```powershell
# 1. Gerar o par de chaves (guardar a chave privada fora do repositório).
python scripts\sign_manifest.py --generate release-key.pem

# 2. Colar a chave pública impressa em config\__init__.py (RELEASE_PUBLIC_KEY).

# 3. Assinar o manifesto antes de publicar.
python scripts\sign_manifest.py --sign release-key.pem release\update-manifest.json
```

Com `RELEASE_PUBLIC_KEY` preenchida, a aplicação rejeita manifestos sem
assinatura válida; sem ela, mantém-se o modelo HTTPS + SHA-256.

