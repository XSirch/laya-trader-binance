# Reavaliação dos candidatos históricos pelas metas por operação

Esta síntese usa ledgers e operações que já estavam calculados; não refaz as buscas de parâmetros nem usa o período de confirmação para selecionar estratégia. Acerto conta PnL líquido positivo; payoff é ganho médio dividido pela perda média absoluta; EV é PnL líquido médio como percentual do notional comprometido na entrada. Os gates atuais são acerto de pelo menos 70%, payoff de pelo menos 1:1, EV estritamente acima de 1,2% por operação e drawdown máximo de 10%.

| Família / recorte | Custo por lado | Operações | Acerto | Payoff | EV líquido/operação | Leitura |
|---|---:|---:|---:|---:|---:|---|
| Multifator Jev, validação | 0,15% | 10 | 40,0% | 1,909 | +0,913% | Payoff bom; acerto e EV abaixo da meta |
| Multifator Jev, confirmação | 0,15% | 10 | 30,0% | 0,543 | -3,279% | Reprovado; DD também excede 10% |
| Multifator Jev, validação / confirmação | 0,25% | 10 / 10 | — | 1,809 / 0,494 | +0,711% / -3,469% | Não passa; confirmação falha todas as metas principais |
| RSI2 diário, calibração H1/2025 | 0,15% / 0,25% | 15 / 15 | 73,33% / 73,33% | 0,708 / 0,629 | +1,040% / +0,837% | Acerto alto em amostra pequena; payoff e EV falham |
| RSI2 diário, validação H2/2025 | 0,15% / 0,25% | 22 / 22 | 54,55% / 54,55% | 1,163 / 1,075 | +0,851% / +0,650% | Falha em acerto e EV; payoff estressado <1 |
| RSI2 diário, combinado 2025–jul/2026 | 0,15% / 0,25% | 37 / 37 | 62,16% / 62,16% | 0,936 / 0,855 | +0,928% / +0,726% | DD 8,28% / 8,75%; confirmação teve zero trades |
| Sweep/reclaim horário + HGB | 0,15% | 106 | 32,1% | 1,100 | -0,583% | Reprovado; DD 17,93% |
| Sweep/reclaim horário + HGB | 0,30% | 42 | 23,8% | 1,090 | -1,080% | Reprovado; DD 13,17% |
| Liquidez cripto + preço, holdout | 0,15% / 0,30% | 48 / 53 | 41,7% / 43,4% | 0,886 / 0,871 | -2,324% / -1,890% | Reprovado; preço isolado também falhou no holdout |
| Macro externo + preço, holdout | 0,15% / 0,30% | 69 / 71 | 44,9% / 42,3% | 0,854 / 0,835 | -1,755% / -2,247% | Reprovado |
| Supertrend horário + ML, holdout | 0,15% / 0,30% | 319 / 226 | 30,1% / 26,1% | 1,576 / 1,460 | -0,494% / -0,879% | Payoff alto, acerto e EV falham |
| Absorção de fluxo 1m, validação | 0,10% / 0,15% | 116 / 116 | 28,45% / 13,79% | 0,306 / 0,176 | -0,232% / -0,332% | Reprovado |
| Continuação de fluxo 1m, gatilho fixo | 0,10% / 0,15% | 3.214 / 3.214 | 30,74% / 23,43% | 0,633 / 0,440 | -0,186% / -0,286% | Reprovado; HGB não selecionou limiar utilizável |
| Rompimento faixa 60m + fluxo, gatilho fixo | 0,10% / 0,15% | 12.095 / 12.095 | 33,78% / 27,30% | 0,597 / 0,416 | -0,202% / -0,302% | Reprovado; HGB também selecionou zero operações |
| Varredura/reclaim 60m em 5m, validação | 0,10% / 0,15% | 22 / 22 | 50,0% / 50,0% | 0,907 / 0,751 | -0,052% / -0,152% | Menos de 30 trades e gates falhos; treino insuficiente |
| Confluência RSI/MACD/Fibonacci/EMA, validação | 0,10% / 0,15% | 52 / 52 | 40,38% / 36,54% | 0,853 / 0,772 | -0,210% / -0,310% | Treino insuficiente para ML; regra fixa falha |
| ML LONG/IDLE/SHORT a cada minuto, validação | 0,10% / 0,15% | 209 / 209 | 42,58% / 38,28% | 0,808 / 0,792 | -0,259% / -0,359% | HGB treinado; nenhum limiar passa |
| Spread relativo 24h, gatilho fixo, validação | 0,10% / 0,15% por ordem/perna | 2.765 / 2.765 | 20,58% / 12,08% | 0,701 / 0,603 | -0,189% / -0,289% | Reprovado; DD adverso 130,63% / 199,76% |
| Spread relativo 24h, HGB, validação | 0,10% / 0,15% por ordem/perna | 0 / 0 | — | — | — | Nenhum threshold de 0,55 a 0,90 selecionou operações |
| Momentum cross-sectional 60m, validação | 0,10% / 0,15% por ordem/perna | 1.978 / 1.978 | 23,05% / 15,52% | 0,814 / 0,717 | -0,201% / -0,301% | Reprovado; DD adverso 99,35% / 148,80% |
| Momentum cross-sectional 60m, HGB, validação | 0,10% / 0,15% por ordem/perna | 0 / 0 | — | — | — | Nenhum threshold de 0,55 a 0,90 selecionou operações |
| Reclaim VWAP + EMA200 15m, validação | 0,10% / 0,15% por ordem | 8.829 / 8.829 | 14,71% / 7,16% | 0,579 / 0,518 | -0,211% / -0,311% | Reprovado; DD adverso 465,98% / 686,70% |
| Reclaim VWAP + EMA200 15m, HGB, validação | 0,10% / 0,15% por ordem | 0 / 0 | — | — | — | Nenhum threshold de 0,55 a 0,90 selecionou operações |

## Outras famílias já testadas

- Convergência spot/perp: somente um cenário operou no período posterior, com uma entrada pareada. A sobra estimada após custo foi 0,136 ponto-base do notional; insuficiente para uma estimativa de acerto/payoff e muito abaixo do EV-alvo. [Relatório de base](basis_research_2026-09-26.md).
- Funding com hedge e seletores de funding foram avaliados principalmente por retorno de carteira e drawdown, sem uma série de operações comparável ao EV por trade solicitado. Os resultados não atendiam ao antigo gate anual e não produzem evidência de 70% de acerto ou EV por operação. [Relatório de derivativos](derivatives_research_2026-09-26.md) e [capacidade de funding](funding_capacity_research_2026-09-26.md).
- Os replays de previsão de payoff, lags, calendário, liquidez e risco de cauda tampouco produziram uma candidata comprovada sob os novos gates; os cortes históricos já foram examinados e não devem ser apresentados como testes prospectivos intocados.
- O observador JEV Spot de um minuto segue separado e com ordens reais desativadas. No último cálculo de ledger disponível, havia zero operações fechadas; isso é falta de amostra, não aprovação nem rejeição estatística.

## Futuros direcionais diários já testados

A recontagem por episódio reproduz o replay de carteira original para todas as 10 regras, nos quatro recortes e nos dois níveis de custo. Nenhuma passa as metas novas em validação e confirmação. A SMA 20/100 teve 72,7% de acerto em apenas 11 episódios na validação; na confirmação caiu para 50%, EV de +0,06% e drawdown de 14,36%. O cross-section 30d e o multifator preservaram DD abaixo de 10% nas duas janelas, mas tiveram acerto de 51,2%/44,3% e 31,3%/56,3%, respectivamente, e nenhum teve EV >1,2% nas duas janelas. [Tabela, custos, método e métricas completas](directional_trade_target_reanalysis_2026-09-27.md).

## Futuros multiativos e filtro ML por episódio

A reanálise de 24 regras antigas de futuros Binance USDT, agora medida por operação, não encontrou uma regra que mantenha todas as metas na validação H2/2025, confirmação jan–jul/2026 e série combinada. `low_volatility30_betahedged` chegou exatamente a 70% de acerto, payoff 1,25 e EV +7,44% em 30 operações na validação, mas a confirmação teve 60,5% de acerto; no combinado, o drawdown foi 16,74%. `rank_blend_betahedged` manteve DD combinado de 8,81%, mas ficou abaixo de 70% de acerto e de payoff 1:1 nas janelas relevantes. EV nesta família é medido sobre o notional inicial da operação, não sobre a margem ou o patrimônio da conta. [Reanálise completa das 24 regras](broad_trade_target_reanalysis_2026-09-27.md).

O experimento distinto de meta-labeling usou HGB para filtrar entradas novas do `rank_blend`, treinando somente com episódios já encerrados e threshold fixo de 70%. No estresse, H2/2025 teve n=17, acerto 58,8%, payoff 1,72, EV +10,15%, DD 5,79%; jan–jul/2026 teve n=20, acerto 70,0%, payoff 0,74, EV +2,31%, DD 5,91%; o combinado teve n=57, acerto 63,2%, payoff 1,25, EV +5,57%, DD 17,29%. O filtro melhora algumas métricas, mas falha amostra mínima em cada janela, payoff na confirmação, acerto nas duas janelas e DD combinado. As probabilidades ainda não têm calibração comprovada e os períodos são retrospectivos, não um holdout futuro. [Protocolo e resultados do filtro ML](episode_ml_meta_filter_research_2026-09-27.md).

## Filtro ML para baixa volatilidade

Apliquei o mesmo HGB e limiar fixo `P(vitória)>=70%` às entradas novas de `low_volatility30_betahedged`, treinando apenas com episódios completos dessa regra encerrados antes de cada sinal. No estresse, a validação H2/2025 ficou em n=23, acerto 65,2%, payoff 1,53, EV +8,29% e DD 6,14%; a confirmação jan–jul/2026 ficou em n=16, acerto 62,5%, payoff 3,15, EV +6,15% e DD 3,91%. O combinado teve n=89, acerto 62,9%, payoff 1,50, EV +8,67% e DD 9,65%. O drawdown melhorou e o payoff/EV passaram, mas o acerto ficou abaixo da meta nas três janelas e a amostra ficou abaixo de 30 nas janelas separadas. Não ajustar o limiar após este resultado. A regra foi escolhida após leitura dos resultados históricos; todas as janelas são retrospectivas, e EV é medido sobre notional inicial, não patrimônio/margem. [Protocolo, resultados e ledger](low_volatility_meta_filter_research_2026-09-27.md).

## Resultado da busca até aqui

Nenhum candidato histórico reavaliado satisfaz todas as metas por operação. O RSI2 diário chegou a 73,33% de acerto na calibração H1/2025, mas payoff 0,708 e EV 1,040% já falham; na validação H2, o acerto caiu para 54,55% e EV 0,851%. Não houve trades na confirmação de 2026. [Reanálise por operação](daily_rsi2_trade_target_reanalysis_2026-09-27.md). O multifator Jev também falha: validação com acerto de 40% e EV de 0,913%, confirmação com payoff 0,543 e EV negativo. Manter splits, custos e regras congelados antes de qualquer observação prospectiva.

Os seis replays intraminuto desta data também falharam os gates. Em particular, o classificador explícito LONG/IDLE/SHORT treinou com 35.098 rótulos independentes horários, mas a validação ficou em 42,6% de acerto e EV de -0,259% no custo-base. Nenhuma mudança de threshold na confirmação foi feita.

O replay de spread relativo entre seis pares de futuros também falhou: em 2025, o gatilho fixo teve 20,58% de acerto e EV de -0,189%; nenhum limiar HGB selecionou operações. O período de 2026 permaneceu diagnóstico estático sem seleção de parâmetros. [Relatório e artefatos](cross_asset_spread_research_2026-09-27.md).

A hipótese de momentum cross-sectional, long no líder e short no retardatário de 60 minutos, também falhou: a regra fixa teve 23,05% de acerto e EV de -0,201% na validação; nenhum limiar HGB selecionou operações. [Relatório e artefatos](cross_sectional_momentum_research_2026-09-27.md).

O reclaim da VWAP móvel a favor da EMA200 de 15 minutos também falhou: teve 14,71% de acerto e EV de -0,211% na validação; nenhum limiar HGB selecionou operações. [Relatório e artefatos](vwap_pullback_research_2026-09-27.md).

## OI intradiário e fluxo taker em BTCUSDT perpétuo

Esta hipótese nova combina expansão de OI e fluxo taker em barras de 5 minutos com direção de preço em 60 minutos, entrada atrasada em 10 minutos, stop de 1 ATR, alvo de 1,3 ATR e timeout de 30 minutos. O treino e a validação foram separados em 20 e 10 dias; todos os limites ficaram congelados antes de abrir resultados.

- Treino: 380 rótulos completos (14 vitórias, 366 perdas), abaixo do mínimo de 500; o HGB não foi ajustado nem abriu operações.
- Regra-base, custo de 0,10% por lado: n=60, acerto 16,7%, payoff 0,195, EV -0,227% por trade e DD 12,78%.
- Regra-base, custo de estresse 0,15% por lado: n=60, acerto 1,7%, payoff 0,616, EV -0,327% e DD 17,87%. Só o mínimo de 30 operações passou.
- Antes de custos, 23/60 operações tiveram PnL positivo e o retorno bruto médio foi -0,027%; houve 34 stops, 17 alvos e 9 timeouts. A regra falhou também antes de considerar apenas o custo como explicação.
- Não ajustei cortes nem saídas usando essa validação. [Protocolo, ledger e proveniência](oi_taker_5m_research_2026-09-28.md).

## Regressão de retorno para o candidato low-volatility

Como extensão distinta do classificador de vitória, o HGB regressor foi treinado apenas com episódios anteriores completos e abriu pernas quando o retorno líquido previsto era >=1,2% do notional. O candidato-base e todas as janelas já tinham sido vistos, então isto continua exploratório.

- Validação H2/2025, estresse: n=23, acerto 69,6%, payoff 1,259, EV +8,61%, DD 6,17%. Faltaram 0,4 ponto percentual no acerto e sete episódios para a amostra mínima de 30.
- Confirmação jan-jul/2026, estresse: n=33, acerto 60,6%, payoff 1,234, EV +4,04%, DD 3,61%. Falha no acerto.
- Combinado, estresse: n=131, acerto 59,5%, payoff 1,277, EV +6,12%, DD 14,64%. Falha no acerto e no drawdown.
- A regressão preservou payoff e EV, mas não tornou o resultado consistente entre janelas. [Protocolo e ledger](low_volatility_ev_forecast_research_2026-09-28.md).

## Barreiras BTC spot recontadas pelas metas por operação

Sem repetir o replay real de BTCUSDT Spot, recontrei os 32 cenários congelados pelo par entrada/saída e líquido de ambas as taxas. Nenhum dos 16 cenários no período posterior passou simultaneamente todos os gates novos.

- HGB, custo-base 0,12% por lado, alocação 50%: n=394, acerto 35,5%, payoff 1,259, EV -0,235% por notional, DD 38,75% e limite adverso 38,96%.
- HGB, custo estressado 0,24% por lado, alocação 50%: n=156, acerto 35,9%, payoff 1,081, EV -0,403%, DD 29,29% e limite adverso 29,56%.
- A recontagem fecha o PnL dos fills com o retorno do ledger-fonte; continua retrospectiva e Spot long-only. [Protocolo e resultado](barrier_payoff_trade_target_reanalysis_2026-09-28.md).

## Hipótese short-only do filtro de EV

A divisão por direção levou a um replay short-only com o mesmo HGB regressor, limiar previsto de 1,2% e notional de 25% do patrimônio. A escolha da direção foi feita após ver o ledger, portanto estes períodos são geração de hipótese, não confirmação.

- Validação H2/2025, estresse: n=17, acerto 82,4%, payoff 1,212, EV +12,93%, DD marcado 8,36%.
- Confirmação jan-jul/2026, estresse: n=22, acerto 72,7%, payoff 2,250, EV +9,42%, DD marcado 4,53%.
- As duas janelas juntas: n=39, acerto 76,9%, payoff 1,745 e EV +10,95%. Cada janela isolada ficou abaixo de 30 operações.
- Combinado jan/2024-jul/2026: n=88, acerto 60,2%, payoff 1,177, EV +5,63% e DD marcado 21,81%; falha acerto, payoff estressado e drawdown.
- É o candidato mais próximo até aqui, mas precisa de teste prospectivo congelado e amostra suficiente antes de qualquer conclusão. [Protocolo e resultado](low_volatility_short_only_research_2026-09-28.md).
