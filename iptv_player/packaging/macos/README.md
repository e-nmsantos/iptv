# Build macOS .app

Este script **tem de ser executado num Mac real** (ou VM/CI macOS) — o PyInstaller
não faz cross-compilation. O build foi testado em macOS 12+.

---

## Requisitos (no Mac)

| Requisito | Comando |
|-----------|---------|
| **Python 3.9+** | `python3 --version` |
| **VLC** | `brew install --cask vlc` ou descarrega de [videolan.org](https://videolan.org/vlc/) |
| **Xcode CLI Tools** | `xcode-select --install` |

## Build (um comando)

```bash
# Na raiz do projeto iptv_player/
bash packaging/macos/build.sh
```

O DMG inclui um atalho para `Applications`. O VLC continua a ser um requisito
separado e tem de estar instalado em `/Applications/VLC.app` também no Mac onde
a app for usada.

O script faz tudo automaticamente:

1. ✅ Verifica pré-requisitos (macOS, VLC, Xcode, Python 3.9+)
2. ✅ Gera o ícone `.icns` automaticamente (se não existir)
3. ✅ Cria um virtualenv `.venv-build` e instala dependências
4. ✅ Compila o `.app` com PyInstaller
5. ✅ Cria o `.dmg` para distribuição

### Output

```
dist/
├── IPTV Player.app     # App bundle (podes arrastar para Applications)
└── IPTV Player.dmg     # Imagem de disco para distribuir
```

## Build sem ter um Mac

O workflow `.github/workflows/build-macos-dmg.yml` cria duas versões no GitHub
Actions: Apple Silicon e Intel.

1. Coloca o projeto num repositório GitHub.
2. Abre **Actions** → **Build macOS DMG** → **Run workflow**.
3. No fim, descarrega o artefacto correspondente ao Mac de destino.

Também é executado automaticamente quando é criada uma tag começada por `v`.

## Primeira execução no Mac

O Gatekeeper vai bloquear a app porque não está assinada com Apple Developer ID:

1. **Botão direito** no `IPTV Player.app` → **Abrir** → **Abrir mesmo assim**
2. Na primeira execução pode demorar mais (PyInstaller extrai binários)

Para distribuir a terceiros sem o aviso do Gatekeeper, precisas de:
```bash
# 1. Código de equipa Apple Developer (https://developer.apple.com)
# 2. Assinar o bundle
codesign --deep --force --verify --verbose \
    --sign "Developer ID Application: O TEU NOME (TEAM_ID)" \
    "dist/IPTV Player.app"

# 3. Enviar para notarização
ditto -c -k --keepParent "dist/IPTV Player.app" "dist/IPTV Player.zip"
xcrun notarytool submit "dist/IPTV Player.zip" \
    --apple-id "teu@email.com" \
    --team-id "TEAM_ID" \
    --password "@keychain:AC_PASSWORD"

# 4. Carimbar (stapling)
xcrun stapler staple "dist/IPTV Player.app"
```

## Ícone personalizado

O `build.sh` gera um ícone automaticamente (gradiente roxo com triângulo play).
Se quiseres um ícone personalizado:

1. Cria um ficheiro `packaging/macos/icon.icns` (formato Apple Icon Image)
2. Ou gera manualmente no Mac:
   ```bash
   pip install Pillow
   python packaging/macos/generate_icon.py
   ```

## Resolução de problemas

### "VLC.app not found"
```bash
brew install --cask vlc
```

### "Xcode Command Line Tools not found"
```bash
xcode-select --install
```

### "Python 3.9+ required"
```bash
brew install python@3.11
```

### Keychain (armazenamento seguro)

A app guarda a chave de cifra no **Keychain do macOS** via `keyring`.
O ficheiro `runtime_hook_keyring.py` força o backend macOS Keychain dentro
do bundle PyInstaller. Se houver problemas de acesso ao Keychain:

```bash
open -a "Keychain Access"
# Procurar por "iptv-player" na lista
```

### Crashes ao abrir — logs

Os logs da app ficam em:
```
~/.config/iptv-player/logs/iptv_player.log
```

### Build falha — voltar a tentar do zero

```bash
rm -rf .venv-build build dist
bash packaging/macos/build.sh
```

## Estrutura dos ficheiros de packaging

```
packaging/macos/
├── build.sh                  # Script de build principal
├── iptv_player.spec          # Configuração PyInstaller
├── generate_icon.py          # Gera ícone .icns (Pillow + iconutil)
├── runtime_hook_keyring.py   # Força backend macOS Keychain
└── README.md                 # Esta documentação
```
