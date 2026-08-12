# Segurança

## Dados locais

Credenciais, MACs, URLs de streams e cabeçalhos sensíveis são cifrados com
AES-GCM. A chave é guardada pelo `keyring` do sistema operativo. A remoção dessa
chave impede a recuperação dos dados cifrados.

Os logs têm rotação automática e aplicam mascaramento a credenciais comuns,
tokens, caminhos Xtream e endereços MAC. Mesmo assim, não publiques logs sem os
rever primeiro.

## Comunicação de vulnerabilidades

Não abras uma issue pública que contenha credenciais, URLs privadas ou dados de
fornecedores. Envia uma descrição mínima ao responsável pelo projeto através de
um canal privado definido no repositório onde a aplicação for publicada.

Inclui versão, sistema operativo, impacto e passos de reprodução sem contas
reais. Revoga imediatamente qualquer credencial exposta.

## Modelo de utilização

A aplicação liga-se apenas às origens introduzidas pelo utilizador. Não fornece
listas nem mecanismos para descobrir ou contornar acesso a conteúdos. Usa apenas
serviços e streams para os quais tenhas autorização.

