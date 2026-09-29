# Diário de execução: price-action alpha independente

## Tentativa 1: dependências no Python global

O Python global não tinha scikit-learn e a primeira chamada via `uv` foi bloqueada ao tentar inicializar o cache padrão fora do workspace. Nenhum replay começou. A execução seguinte usou cache e ambiente temporários em `%TEMP%` com o extra `tree-research`; nenhuma dependência foi adicionada ao repositório.

## Tentativa 2: relatório com valor infinito

Os oito cenários terminaram, mas a serialização JSON parou porque as posições do controle buy-and-hold tinham níveis de stop/alvo infinitos. Nenhuma métrica dessa tentativa foi aceita. O controle não possui barreiras; o serializador agora grava esses níveis como nulos. Também foi corrigido o cálculo do limite adverso intrahorário para capturar máxima e mínima OHLC antes da resolução da barreira.

## Replay final

O protocolo permaneceu igual. A execução gerou 1.325 eventos, 905 previsões, 44 auditorias mensais e os 8 cenários completos. O HGB gated teve retorno de -14,45% e drawdown adverso de 18,24% a custo de 0,15% por lado; a 0,30%, retorno -10,80% e drawdown adverso de 13,33%. O controle all-sweeps perdeu 57,56% e 78,49%. O resumo e as curvas estão em `price_action_alpha_research_2026-09-27.json` e `results/price_action_alpha_research.json`.

Hash final do relatório: `c4495377621eba12f43c629810ce21d021a99251d0e0286ea48c68b19433ab87`. Hash final dos insumos: `1b6528ff174899f3385b156bb1a0b3c19da730f09c0ed57aceaaca4fd90173ed`. Nenhuma ordem foi enviada e não houve chamada JEV. Resultado: `goal_achieved=false`, `deployable=false`.
