# C14 — Resultados da expectativa decomposta

Data: 28/09/2026  
Status: estudo retrospectivo reprovado como seletor; nenhuma estratégia foi validada.

## Resultado

O previsor decomposto não encontrou entradas sob o corte econômico pré-registrado. Em oito folds mensais, pontuou 1.977 candidatos e emitiu 1.977 previsões finitas, sem abstenção por falta de dados. Nenhuma previsão superou estritamente 1,2%; o maior EV previsto foi **0,7135%**. O replay executou zero operações.

| Métrica | C06 direto congelado | C14 decomposto |
|---|---:|---:|
| Candidatos acima de `EV > 1,2%` | 19 | 0 |
| Operações executadas | 11 | 0 |
| EV-base por operação | 1,2617% | indefinido — sem operações |
| Acerto | 27,27% | indefinido — sem operações |
| Payoff | 10,17 | indefinido — sem operações |
| Profit factor | 4,35 | indefinido — sem operações |
| PnL no stress | +US$ 380,50 | US$ 0,00 sem exposição |
| Drawdown-base | 2,39% | 0% sem exposição |
| Semanas ativas | 6 | 0 |

O C06 cumpre EV-base, payoff, profit factor e PnL stress no pequeno replay observado, mas fica muito abaixo das 200 operações e das oito semanas ativas. A taxa de acerto também ficou longe da preferência próxima de 70%. O drawdown zero do C14 é consequência de não operar e não representa desempenho. Nenhuma das duas linhas demonstra consistência ou passa todos os gates.

## Diagnóstico do seletor

- EV previsto médio: **−0,2841%**; retorno realizado médio dos 1.977 candidatos: **−0,2155%**.
- Mediana do EV previsto: −0,2560%; percentil 90: −0,1185%; percentil 99: +0,0889%; máximo: +0,7135%. Todos ficam abaixo de +1,2%.
- No decil superior de score, os 198 candidatos tiveram EV previsto médio de **−0,0251%**, retorno líquido realizado médio de **−0,0719%** e acerto de 17,17%. O decil inferior realizou −0,6589%, então houve alguma ordenação relativa, mas o melhor grupo continuou negativo.
- O decil superior do score direto C06 previa em média +0,5691%, mas realizou −0,0883%. Também não exibiu EV realizado positivo nesse grupo.
- Para `p`, o Brier foi 0,118605, contra 0,118653 para uma previsão constante igual à taxa observada de 13,76%; a melhora de 0,000048 é mínima. Houve 272 retornos positivos e 1.705 não positivos.
- Nos positivos, `G` previsto médio foi 1,0846%, abaixo dos 1,5283% realizados. Nos não positivos, `L` previsto médio foi 0,4925%, próximo da magnitude observada de 0,4936%.

O limite superior de EV não alcançou o corte em nenhum mês. Os 100 controles aleatórios pareados, pré-registrados para o caso de existir seleção, eram inaplicáveis com zero candidatos aprovados; nenhum foi executado.

## Execução e integridade

- Mercado e universo: Binance USD-M, BTCUSDT e ETHUSDT; rompimento/continuação do C06, stop ATR15m, cooldown e saída `trend_loss` mantidos.
- Janela: 02/01/2026 a 01/09/2026 UTC, fim exclusivo. Os labels do treino foram maturados antes de cada refit mensal, com purge de 24 horas. A calibração usou apenas os 90 dias anteriores a cada corte.
- Componentes: classificador CUDA para `p`, regressões CUDA para `G` e `L`; os componentes foram calibrados somente no bloco histórico anterior ao fold. O corte `> 0,012` não foi alterado.
- Foram treinados 48 modelos com XGBoost CUDA/hist: três provisórios e três finais em cada um dos oito folds. Os 24 modelos finais foram salvos. Nenhum fallback para CPU ocorreu.
- O replay do controle C06 reconciliou com o relatório salvo em todas as métricas verificadas. Os hashes de cada saída conferem com a lista do `research.json`.
- Dataset: SHA-256 `cd09bd04a01c7de294438415df17fb26f86d346f10fc1c21ececbb4de0d84691`; manifesto: `370539d1379221bb5a5cdbbb2ff9de30530616cd82b1b638c58f136110f651f4`.
- Ordens reais: nenhuma. O resultado é retrospectivo, usa a mesma janela já examinada em C05/C06/C12/C13 e não é validação independente.

## Verificação da proposta C12

A busca no inventário confirmou que a equação `pG-(1-p)L` ainda não havia sido registrada como experimento, implementada ou treinada. O código anterior tinha classificador e uma única regressão direta; não estimava separadamente os tamanhos condicionais de ganhos e perdas. A proposta C12 distingue corretamente essas abordagens.

O C13 encontrou EV acima do alvo apenas no ranking-oráculo conjunto de BTC e ETH, que usa retornos realizados para ordenar candidatos e não pode ser executado. Os limites isolados por contrato ficaram abaixo do alvo. O C14 testou a hipótese de que a estimativa decomposta recuperaria uma ordenação útil e não confirmou isso com a regra econômica congelada.

## Decisão

Rejeitar o EV decomposto como seletor nesta configuração. Não baixar o corte, não escolher outros quantis de score e não buscar outra calibração nesta mesma janela: isso seria ajuste retrospectivo. O controle C06 também continua exploratório, devido à amostra curta. O próximo estudo deve usar uma família não duplicada e/ou dados futuros ainda não observados, com protocolo, gates e período congelados antes de qualquer avaliação.

## Artefatos

- Pré-registro: [`CICLO14_EV_DECOMPOSTO_PROTOCOLO_2026-09-28.md`](CICLO14_EV_DECOMPOSTO_PROTOCOLO_2026-09-28.md)
- Resultados e hash ledger: `research/results/cycle14_ev_decomposed_2026-09-28/research.json`
- Scores fora do treino: `research/results/cycle14_ev_decomposed_2026-09-28/walk_forward_scores.csv`
- Diagnóstico por decil: `research/results/cycle14_ev_decomposed_2026-09-28/score_deciles.csv`
- Replays do C06 e C14: `research/results/cycle14_ev_decomposed_2026-09-28/*trades_*.csv`
- Modelos finais: `research/results/cycle14_ev_decomposed_2026-09-28/models/`

