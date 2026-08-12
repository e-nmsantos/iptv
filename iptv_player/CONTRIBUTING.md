# Contribuir

1. Cria um ambiente virtual e instala `requirements-dev.txt`.
2. Não uses fornecedores ou credenciais reais em testes.
3. Mantém todos os testes de rede limitados a servidores locais simulados.
4. Antes de propor alterações, executa:

```bash
python -m pytest
python -m ruff check src tests
python -m compileall -q main.py config src tests
```

Alterações ao esquema SQLite devem ser aditivas, transacionais e acompanhadas
por um teste que abra uma base de dados da versão anterior. Alterações de rede
devem ter timeout, cancelamento, limites de resposta e mensagens sem segredos.

