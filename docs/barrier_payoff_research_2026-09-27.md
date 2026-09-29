# Resultado: previsão do payoff com stop, alvo e prazo

Execução em 27/09/2026, UTC. Esta família foi rejeitada: nenhum dos 32 cenários atingiu ao mesmo tempo o alvo local de CAGR líquido de 50% e drawdown máximo de 10%. Não houve seleção de vencedor nem mudança do candidato de acompanhamento prospectivo.

## Desenho e integridade

O protocolo fixou BTCUSDT spot, entrada na abertura após uma hora de atraso, stop de 1 ATR, alvo de 2 ATR e timeout de oito horas. A previsão mensal usou somente rótulos cuja disponibilidade era estritamente anterior ao corte. A regra financeira não sobrepôs posições. A grade cruzou média móvel do payoff, HistGradientBoostingRegressor, entrada sempre que elegível e buy-and-hold, com 0,12% ou 0,24% por lado e alocações de 50% ou 100%, nos períodos de desenvolvimento e posterior.

Os 712 arquivos ZIP e os três manifestos locais foram verificados; os estados congelados contêm 30.695 horários e 114 campos. A execução usou os arquivos locais, fez zero downloads, zero chamadas pagas e enviou zero ordens. Os 44 testes dos três módulos desta hipótese passaram. Os hashes de entrada, código, protocolo, dependências e relatório são preservados em `results/barrier_payoff_inputs.json`, `results/barrier_payoff_research.json` e [na síntese JSON](barrier_payoff_research_2026-09-26.json). Recalculei as âncoras ao final: continuam iguais às entradas congeladas; o hash do relatório completo confere; o erro máximo de reconciliação do ledger foi `4,56e-14`.

## Resultado econômico

CAGR líquido e drawdown máximo, em porcentagem, para o custo principal de 0,12% por lado:

| Regra | Alocação | Desenvolvimento: CAGR / queda | Posterior: CAGR / queda | Entradas posteriores |
|---|---:|---:|---:|---:|
| Média do payoff | 50% | 0,00 / 0,00 | 0,00 / 0,00 | 0 |
| Média do payoff | 100% | 0,00 / 0,00 | 0,00 / 0,00 | 0 |
| HGB | 50% | -5,05 / 5,47 | -16,29 / 38,75 | 394 |
| HGB | 100% | -9,90 / 10,69 | -30,52 / 63,31 | 394 |
| Sempre que elegível | 50% | -50,32 / 50,52 | -91,29 / 99,85 | 5.397 |
| Sempre que elegível | 100% | -75,55 / 75,74 | -99,27 / 100,00 | 5.397 |
| Comprar e manter | 50% | 25,34 / 5,37 | 14,27 / 40,23 | 1 |
| Comprar e manter | 100% | 50,69 / 10,75 | 26,06 / 53,74 | 1 |

O cenário de 100% em desenvolvimento supera 50% de CAGR, mas excede o limite de drawdown e cai para 26,06% de CAGR com drawdown de 53,74% no período posterior. Buy-and-hold, portanto, não atende ao objetivo de risco ou à consistência temporal. Com 50% de alocação, o retorno posterior é positivo, mas a queda observada continua muito acima de 10%.

No período posterior, o HGB teve MSE de `8,03e-5`, contra `7,74e-5` da média móvel do payoff; a previsão média teve menor erro. A média não gerou entradas acima do limiar de custo em nenhum dos cenários. O controle que entra sempre perdeu quase todo o capital posterior, e o HGB também perdeu dinheiro nos dois custos e alocações. O custo estressado reduziu algumas perdas principalmente por reduzir entradas; não converteu a regra em resultado positivo consistente.

## Decisão e próximo experimento

Não ajustar ATR, prazo, limiares ou modelo depois de ver esta grade. Isso criaria outra tentativa sobre o mesmo histórico. A família permanece rejeitada como estratégia candidata.

A rodada seguinte investigará se retornos e fluxo agressor defasados de BTC/ETH acrescentam informação a previsões de outros ativos, sob o atraso de execução já fixado. A nota de fontes separa essa hipótese dos estudos prévios de modelos próprios por ativo e dos testes semanais de risco relativo; não afirma que o efeito sobreviva a custos ou ao atraso local. Todas as janelas históricas do projeto já foram examinadas, então um resultado favorável futuro ainda será retrospectivo. A validação prospectiva continuará indispensável.

## Limites

Os rótulos horários se sobrepõem e não são trades independentes. O estudo trata retornos brutos de episódio e candles OHLC; ordem intrabar de stop/alvo, gaps e fills são hipóteses explícitas, não cotações executáveis. Taxas, spread, deslizamento, capacidade e disponibilidade histórica ponto a ponto não foram confirmados para uma conta. Os resultados não são uma confirmação prospectiva nem autorizam ordens reais.
