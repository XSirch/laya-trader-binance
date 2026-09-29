# Primeiro ciclo de treino e walk-forward — 28/09/2026

## Decisão

**Nenhuma fórmula foi aprovada.** XGBoost treinou na RTX 4070 Laptop com CUDA e foi
comparado ao HistGradientBoosting em CPU. Nenhum fold cumpriu EV líquido acima de 1,2%,
payoff mínimo de 1:1, amostra suficiente e resultado positivo sob custos estressados.
Os retornos de teste ficaram negativos nos folds com operações; onde não houve operação,
isso também não conta como evidência de consistência.

Não enviar sinais de pesquisa para execução real. Os artefatos registram
`target_not_demonstrated` e mantêm a saída em abstenção.

## Dados e protocolo

- Somente pares Binance BTCUSDT e ETHUSDT, em Spot e USD-M perpétuo; candles de um minuto.
- 2.157.120 linhas por mercado, de 13/08/2024 00:00 UTC até 01/09/2026 00:00 UTC, fim
  exclusivo. Ambos os datasets passaram pela validação de continuidade e pelo manifesto
  SHA256 de arquivos oficiais.
- O trecho anterior a 13/08/2024 foi excluído: os marks USD-M oficiais estão sem os
  minutos 12/08/2024 10:02 e 10:03 UTC. A lacuna consta no
  [issue #483 do repositório oficial](https://github.com/binance/binance-public-data/issues/483).
- A lacuna de marks de 29/06/2026 foi recuperada dos arquivos diários oficiais de BTC e
  ETH, ambos com 1.440 linhas e checksum verificado. Nenhum preço foi interpolado.
- Custos por lado: Spot 10 bp de taxa + 5 bp de slippage; USD-M 5 bp + 5 bp. O estresse
  dobra taxa e slippage. USD-M usa funding observado, marks para monitoramento e uma
  posição global por modelo/mercado.
- Dois folds com treino, calibração, seleção e teste em ordem temporal estão em
  `configs/walk_forward.usdm_exploratory.json`. Os mesmos limites foram usados em Spot.
  Os testes são exploratórios: partes de 2025–2026 já haviam sido examinadas em pesquisas
  anteriores do projeto.
- Gates atuais: EV líquido >1,2% por nocional; payoff >=1:1; acerto próximo de 70% como
  preferência; drawdown sem teto, reportado e minimizado entre aprovados. A qualificação
  também exige 200 operações, 8 semanas ativas, profit factor >=1,25 e resultado positivo
  com custos estressados.
- Suíte de software: 57 testes passaram, incluindo a verificação de treino CUDA e a
  recuperação de marks somente por arquivo diário verificado. Isso não aprova uma
  estratégia financeira.

## Resultados

EV é o retorno líquido médio por operação sobre o nocional inicial. Drawdown e retorno
acumulado são sobre o patrimônio inicial simulado de US$ 10.000.

| Mercado/modelo | Fold | Corte escolhido | Seleção: operações; acerto; EV; payoff | Teste: operações; acerto; EV; payoff; drawdown |
|---|---:|---:|---|---|
| Spot / XGBoost CUDA | 1 | 0,40 | 1; 0%; -0,189%; indefinido | 1; 0%; -0,064%; indefinido; 0,25% |
| Spot / XGBoost CUDA | 2 | 0,35 | 0; sem amostra | 0; sem amostra |
| USD-M / XGBoost CUDA | 1 | 0,40 | 18; 33,3%; -0,281%; 0,439 | 42; 40,5%; -0,064%; 1,125; 2,36% |
| USD-M / XGBoost CUDA | 2 | 0,35 | 13; 61,5%; +0,116%; 1,100 | 31; 25,8%; -0,288%; 0,791; 3,36% |
| USD-M / HGB CPU | 1 | 0,35 | 38; 18,4%; -0,389%; 0,651 | 36; 44,4%; -0,071%; 0,925; 2,22% |
| USD-M / HGB CPU | 2 | 0,35 | 21; 42,9%; -0,016%; 1,234 | 36; 25,0%; -0,300%; 0,777; 4,17% |

O melhor EV de seleção foi +0,116% em apenas 13 operações; no teste seguinte o EV caiu
para -0,288%, com acerto de 25,8%. Nenhum resultado chega perto do EV exigido de +1,2%
por operação. Os testes com custos dobrados também perderam dinheiro. O caso Spot teve
uma ou nenhuma operação por fold; ausência de sinais não prova que o mercado seja
impossível, mas mostra que o modelo não sustentou frequência mínima.

O baseline sem filtro ML também foi negativo após custos. Na seleção do primeiro fold,
Spot fez 2.013 operações, EV -0,289%, payoff 0,673 e drawdown 91,8%; USD-M fez 3.519,
EV -0,294%, payoff 0,761 e drawdown 98,8%. Com taxas e slippage zerados, os EVs médios
foram somente +0,011% em Spot e +0,003% em USD-M. Portanto, aumentar o tamanho da posição
não corrige a expectativa; os gatilhos e as saídas precisam encontrar movimentos brutos
muito maiores, com menos giro.

## O que o ML sugere

Nos dois folds CUDA, `stop_fraction` e `atr_pct` ficaram entre as variáveis de maior ganho;
também apareceram volatilidade realizada, distâncias de Fibonacci e tendências de 15m/1h.
Isso sugere testar filtros de volatilidade/risco e a interação de retração com tendência.
Importância de árvore é apenas uma pista descritiva, não uma relação causal nem prova de
vantagem lucrativa. O classificador USD-M teve taxa positiva de rótulos perto de 26–29%,
e o regressor previu R líquido negativo para quase todos os candidatos do primeiro
fold. O ML não encontrou sinal suficiente para aprovar entradas.

## Hipóteses para o próximo ciclo

1. Redesenhar a saída: testar alvos mais distantes e time stops mais longos na seleção,
   mantendo o risco por operação limitado; a taxa de acerto pode cair se payoff e EV
   melhorarem fora da amostra.
2. Reduzir giro e procurar movimentos brutos maiores. O diagnóstico sem custos mostra que
   as regras atuais quase não têm expectativa bruta, antes mesmo de pagar execução.
3. Congelar um filtro por volatilidade e tendência, medir resultado por estratégia,
   direção e ativo, e só depois refazer os labels e treinar o classificador/regressor.
4. Não usar 2025–2026 como teste realmente inédito. Depois que uma hipótese sobreviver à
   seleção e aos folds históricos, coletar um período prospectivo novo em paper e
   reconciliar sinais, fills, taxas e funding antes de qualquer decisão de execução.

## Artefatos

- Dataset USD-M e manifesto: `data/usdm_btc_eth_1m/`
- Dataset Spot e manifesto: `data/spot_btc_eth_1m/`
- Treino CUDA USD-M: `results/usdm_cuda_lowercut/`
- Treino CPU de referência USD-M: `results/usdm_cpu_lowercut/`
- Treino CUDA Spot: `results/spot_cuda_exploratory/`
- Fold dates: `configs/walk_forward.usdm_exploratory.json`
