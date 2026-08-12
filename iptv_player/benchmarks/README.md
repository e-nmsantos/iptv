# Benchmark de catálogos

Este benchmark cria catálogos sintéticos numa base temporária. Não usa rede,
credenciais nem dados de fornecedores.

```powershell
python -m benchmarks.catalog_benchmark --sizes 10000 50000 100000
```

Na CI agendada é usado `--enforce-budget`: para 100 mil itens limita inserção a
240 s, página e pesquisa a 500 ms, contagem a 200 ms e pico de memória a 256 MiB.

São medidos a gravação cifrada, a primeira página de 250 itens, uma pesquisa
FTS5 e a contagem total. Os números dependem do disco e do CPU, por isso servem
para detetar regressões na mesma máquina e não como promessa universal.

Baseline Windows, Python 3.13, 11 de agosto de 2026, antes da atualização da
coluna de pesquisa para FTS5: 100 000 itens, inserção 91,596 s, primeira página
0,1017 s, pesquisa por substring 0,1371 s, contagem 0,0102 s e pico 43,7 MiB.

Com FTS5 medido diretamente: inserção 90,809 s, primeira página 0,1199 s,
pesquisa 0,0325 s, contagem 0,0098 s e pico 43,7 MiB. A pesquisa ficou cerca de
quatro vezes mais rápida nesta baseline.
