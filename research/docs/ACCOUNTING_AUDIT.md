# Auditoria de contabilidade e replay — 28/09/2026

## Escopo

Reproduzi os trades já salvos dos modelos `spot_cuda_exploratory`, `usdm_cuda_lowercut` e `usdm_cpu_lowercut`, nos folds 1 e 2, com custos-base e estressados. Não treinei modelos, não ajustei thresholds, não consultei APIs externas e não enviei ordens.

O script congelado da auditoria é [`../scripts/accounting_audit.py`](../scripts/accounting_audit.py). Ele carregou os artefatos locais confiáveis, validou o hash do dataset normalizado e comparou cada replay com o ledger e o relatório originais. Fontes e hashes de modelos, relatórios e dados constam em [`../results/accounting_audit_2026-09-28/audit_summary.json`](../results/accounting_audit_2026-09-28/audit_summary.json).

| Mercado | Dataset | Símbolos | Período | Recibos de arquivos-fonte |
|---|---:|---|---|---:|
| Spot | 2.157.120 candles | BTCUSDT, ETHUSDT | 13/08/2024 a 01/09/2026 (fim exclusivo) | 64 |
| USD-M | 2.157.120 candles | BTCUSDT, ETHUSDT | 13/08/2024 a 01/09/2026 (fim exclusivo) | 194 |

Os hashes dos dados normalizados são `f7f0e3685b11dd8159fc48c18fb9d3bf47be3dee98b8758aeae7ac3d51c26530` (Spot) e `cd09bd04a01c7de294438415df17fb26f86d346f10fc1c21ececbb4de0d84691` (USD-M). O XGBoost salvo declara treino em `cuda:0`; o comparador HGB declara treino em CPU. O método `TrainedGate.score` move os estimadores XGBoost para CPU na inferência.

## Reconciliações

- **300 linhas de ledger** foram reproduzidas: cada trade salvo coincidiu por símbolo, lado, estratégia, horário, fill, notional, retorno líquido, R e PnL. As linhas repetem sinais entre modelos/folds e entre custos; não representam 300 operações independentes.
- A decomposição fecha como `PnL líquido = PnL de preço a referência - slippage adverso - comissão - custo assinado de funding`. Funding negativo representa crédito líquido.
- Maior erro absoluto dessa decomposição: `7,11 × 10⁻¹⁵ USD`. Maior diferença entre PnL recalculado e CSV salvo: `0 USD`.
- Em cada um dos 12 arquivos de avaliação, a soma de PnL bate com a mudança de patrimônio final; o maior desvio observado foi `7,4 × 10⁻¹² USD`. `notional × retorno líquido` também reproduziu o PnL.
- O sizing respeitou o orçamento calculado de stop mais fricção; excesso máximo por arredondamento: `3,6 × 10⁻¹⁵ USD`.
- A feature registra o horário de decisão no fechamento do candle (`open_time + 1 min`). Esse horário coincide com a abertura seguinte usada na entrada. A auditoria não encontrou defasagem adicional.

O ledger detalhado está em [`../results/accounting_audit_2026-09-28/trade_cost_decomposition.csv`](../results/accounting_audit_2026-09-28/trade_cost_decomposition.csv). O replay-base e o stress podem executar conjuntos e quantidades diferentes; portanto, eles não formam sozinhos um ledger contrafactual pareado que isole cada custo mantendo o mesmo trade.

## Resultado econômico confirmado

EV abaixo é o retorno líquido médio por operação sobre o nocional inicial, em porcentagem. Drawdown é o do replay original, calculado com patrimônio marcado em fechamento de minuto e saídas executadas.

| Modelo / fold | Base: n; EV; acerto; payoff; PF; DD | Stress: n; EV; acerto; payoff; PF; DD |
|---|---|---|
| Spot XGBoost CUDA / 1 | 1; −0,064%; 0%; n/a; 0,00; 0,25% | 1; −1,039%; 0%; n/a; 0,00; 0,23% |
| Spot XGBoost CUDA / 2 | 0; n/a; n/a; n/a; n/a; 0% | 0; n/a; n/a; n/a; n/a; 0% |
| USD-M XGBoost CUDA / 1 | 42; −0,064%; 40,5%; 1,125; 0,687; 2,36% | 44; −0,270%; 22,7%; 1,108; 0,298; 3,93% |
| USD-M XGBoost CUDA / 2 | 31; −0,288%; 25,8%; 0,791; 0,297; 3,36% | 32; −0,515%; 15,6%; 0,648; 0,121; 4,52% |
| USD-M HGB CPU / 1 | 36; −0,071%; 44,4%; 0,925; 0,712; 2,22% | 40; −0,301%; 22,5%; 0,962; 0,263; 4,34% |
| USD-M HGB CPU / 2 | 36; −0,300%; 25,0%; 0,777; 0,298; 4,17% | 37; −0,513%; 16,2%; 0,621; 0,129; 5,07% |

Nenhum fold chega perto de EV `>1,2%`; os folds ativos também ficam abaixo de 200 operações, e todos os replays estressados terminam negativos. O acerto é reportado como preferência, sem reprovar por si só. Um drawdown pequeno não compensa EV negativo.

Não somei operações de folds, backends ou custos para tentar alcançar a amostra mínima. Os períodos são retrospectivos e não constituem evidência prospectiva.

## Complemento P0: funil e trajetória

[signal_funnel.csv](../results/accounting_audit_2026-09-28/signal_funnel.csv) conserva o resumo agregado da auditoria inicial. O complemento [funnel_detail.csv](../results/p0_completion_2026-09-28/funnel_detail.csv) agora conta a primeira rejeição por ativo, estratégia, direção e regime, desde prontidão/volatilidade/volume, setup, cooldown e limite de stop até probabilidade, retorno esperado, posição aberta e execução. As condições foram espelhadas do gerador vigente; os conjuntos de candidatos foram comparados em cada mercado, ativo e janela, e qualquer divergência interromperia a execução.

As contagens anteriores à geração são oportunidades candle × estratégia × lado, não operações independentes. Nas janelas avaliadas, o gerador emitiu 14.032 candidatos Spot e 42.361 USD-M antes dos filtros do modelo.

O ledger [paired_cost_ledger.csv](../results/p0_completion_2026-09-28/paired_cost_ledger.csv) mantém cada trade-base, quantidade, timestamps, saída e funding observado fixos e recalcula taxas/slippage em dobro. Os 146 pares reconciliam o braço-base. O EV pareado por nocional inicial foi negativo em todos:

| Mercado/modelo | Fold | Trades pareados | EV base | EV stress pareado |
|---|---:|---:|---:|---:|
| Spot XGBoost CUDA | 1 | 1 | −0,064% | −0,364% |
| USD-M XGBoost CUDA | 1 | 42 | −0,064% | −0,264% |
| USD-M XGBoost CUDA | 2 | 31 | −0,288% | −0,488% |
| USD-M HGB CPU | 1 | 36 | −0,071% | −0,271% |
| USD-M HGB CPU | 2 | 36 | −0,300% | −0,501% |

Esse contrafactual isola taxas/slippage sobre a trajetória-base; o replay integral estressado permanece separado porque pode mudar entradas, saídas, quantidades e conjunto de operações. A tabela de resultado econômico acima continua sendo o teste integral.

[portfolio_diagnostics.csv](../results/p0_completion_2026-09-28/portfolio_diagnostics.csv) e [monthly_equity_returns.csv](../results/p0_completion_2026-09-28/monthly_equity_returns.csv) acrescentam retorno mensal, equity marcada a cada minuto, drawdown de fechamento, minutos em posição, exposição enquanto posicionado e caixa médio ocioso. Nos folds USD-M, houve posição em 0,14%–0,39% dos minutos avaliados; quando posicionados, o notional médio ficou em 28%–40% do patrimônio. A maior parte do período ficou em caixa por baixa frequência e pelo bloqueio de uma posição global por mercado, não por uma vantagem econômica demonstrada.

[path_bound_diagnostics.csv](../results/p0_completion_2026-09-28/path_bound_diagnostics.csv) separa excursões de candles completos anteriores da excursão ambígua no candle de saída e mede fricção em relação ao risco planejado do stop. A fricção média de execução consumiu 50,6% do risco planejado nas operações USD-M base e 55,5% na única operação Spot; o funding assinado é mostrado separadamente. MFE/MAE e drawdown não resolvem a sequência de eventos dentro do minuto.

## Limites remanescentes da auditoria

1. O OHLC de 1 minuto não revela a ordem dos movimentos dentro do candle de saída; excursões desse candle continuam marcadas como ambíguas.
2. A auditoria usa fills simulados e taxas configuradas, não fills nem tarifas da conta. Em USD-M, o funding segue a convenção conservadora de mark price do simulador.
3. Spot e USD-M foram medidos separadamente; não foi criado um portfólio conjunto com margem/liquidação ou limites de exposição compartilhados.

A contabilidade, o funil, o contrafactual de custos e as métricas temporais exigidas para o P0 foram reproduzidos nos artefatos congelados. O estado econômico continua target_not_demonstrated; nenhum resultado habilita ordens reais nem comprova rentabilidade futura. A síntese verificável está em [p0_completion_summary.json](../results/p0_completion_2026-09-28/p0_completion_summary.json).
