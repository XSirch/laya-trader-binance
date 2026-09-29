# C16 — Resultado da transferência congelada C06 para BNB/SOL

Data: 28/09/2026  
Status: reprovado como estratégia; o resultado histórico não valida consistência.

## Decisão

O score C06 não transferiu para BNBUSDT e SOLUSDT com valor econômico positivo nesta janela. O portfólio BNB/SOL perdeu dinheiro na base e no stress. Ao juntá-lo a BTC/ETH, o PnL permaneceu positivo, mas o EV-base caiu de 1,2617% para 0,4030% por operação e a amostra ficou em 23 operações. Nenhum portfólio alcançou 200 operações; nenhum passou todos os gates.

Manter o C06 apenas como hipótese exploratória em BTC/ETH. Não baixar o corte, remover SOL, mudar a janela ou selecionar outra combinação com estes resultados. Nenhuma ordem real foi enviada.

## Resultados

| Métrica | Controle C06: BTC/ETH | Transferência: BNB/SOL | Universo conjunto: 4 contratos |
|---|---:|---:|---:|
| Candidatos pontuados | 1.977 | 2.175 | 4.152 |
| Eventos selecionados (`score > 1,2%`) | 19 | 22 | 41 |
| Operações executadas, base | 11 | 14 | 23 |
| EV líquido médio por operação, base | +1,2617% | −0,4083% | +0,4030% |
| Acerto, base | 27,27% | 7,14% | 17,39% |
| Payoff, base | 10,17 | 4,12 | 8,36 |
| Profit factor, base | 4,35 | 0,39 | 2,01 |
| PnL-base | +US$ 575,01 | −US$ 177,99 | +US$ 427,08 |
| Drawdown máximo, base | 2,39% | 2,27% | 2,39% |
| Semanas ativas | 6 | 10 | 14 |
| PnL sob stress | +US$ 380,50 | −US$ 203,06 | +US$ 210,00 |
| Passou todos os gates | Não | Não | Não |

O stress dobra taxas e slippage; o funding observado permanece no replay. O EV usa retorno líquido sobre o notional inicial. O replay usa US$ 10.000 iniciais, risco de 0,25% por operação, notional máximo de 1,0x do equity e uma posição global.

O subconjunto de eventos transferidos teve resultados negativos nos dois contratos: BNB selecionou 13 eventos, dos quais 2 foram positivos, com média líquida de −0,2247%; SOL selecionou 9, nenhum positivo, com média de −0,7044%. No portfólio conjunto executado, ETH respondeu por +US$ 615,17 de PnL e as perdas líquidas dos outros três contratos reduziram o total para +US$ 427,08. Portanto, o lucro combinado não demonstra transferência ou diversificação do seletor.

### Gates

- **BNB/SOL:** 14 operações, 10 semanas ativas; EV-base abaixo de 1,2%; profit factor abaixo de 1,25; stress negativo. Falhou quatro gates.
- **BTC/ETH/BNB/SOL:** 23 operações, 14 semanas; payoff, profit factor e stress positivos, mas EV-base abaixo de 1,2% e amostra abaixo de 200. Falhou os gates de EV e amostra.
- **Preferência de acerto:** nenhum portfólio se aproximou de 70%. Isso continua sendo diagnóstico, não um piso.
- **Drawdown:** foi medido, sem teto imposto. A amostra não permite escolher uma estratégia aprovada por drawdown.

## Método e reconciliação

- Foram aplicadas as regras C06 sem retreino ou calibração em BNB/SOL: rompimento de 1 minuto, lookback de 300 minutos, confirmação de volume, cooldown de 15 minutos, contexto de 1h/4h, stop ATR de 15 minutos, saída `trend_loss`, horizonte de 1.440 minutos e corte estrito `> 0,012`.
- Usaram-se os oito modelos mensais C06 de XGBoost treinados em CUDA. A inferência também foi executada em CUDA, preservando o dispositivo de inferência do C06.
- Os 1.977 scores BTC/ETH foram reproduzidos em todos os oito folds; erro absoluto máximo `9,975e-17`, contra tolerância pré-registrada de `1e-8`. Os replays C06 base e stress reconciliaram com o relatório de origem dentro de `1e-9`.
- Janela avaliada: 02/01/2026 a 01/09/2026 UTC, fim exclusivo. As entradas nas últimas 24 horas foram censuradas para maturação dos rótulos.
- Dados BNB/SOL: 875.520 candles de 1 minuto, de 01/11/2025 a 01/09/2026 UTC; 437.760 minutos por contrato. O aquecimento de novembro/dezembro ficou fora da seleção. Candles, mark price e funding vieram de 62 arquivos/receipts Binance Vision com SHA-256 verificado; candles foram validados como contínuos, sem completar lacunas sinteticamente.
- Taxas-base USD-M: 5 bps, mais slippage de 5 bps por lado; stress dobra ambos. Funding foi aplicado nos horários observados. O custo é uma hipótese do simulador e não substitui medição de execução real.
- Não houve treinamento neste ciclo, envio de ordens ou validação prospectiva. O histórico de janeiro–agosto de 2026 já foi inspecionado para BTC/ETH; a expansão para BNB/SOL é um teste retrospectivo de transferência, não uma amostra temporal futura independente.

Durante a execução ocorreram três correções técnicas de runner, todas registradas no ledger antes da retomada correspondente: inferência CPU foi substituída por inferência CUDA para reproduzir os scores; corrigiu-se o acesso à configuração USD-M no diagnóstico evento a evento; e o hash do manifesto passou a ser lido diretamente do arquivo. A última retomada recalculou os dez CSVs e confirmou que cada hash era idêntico ao artefato parcial já escrito antes da falha do gerador de relatório. Nenhum limiar, modelo, regra de seleção ou gate mudou.

## Veredito sobre a proposta após C12

A proposta identificou corretamente que o C06 tinha apenas 11 operações e estava concentrado nos grandes ganhos, e distinguiu expectativa decomposta (`p*G-(1-p)*L`) da regressão direta anterior. O C14 executou essa hipótese com GPU e não emitiu nenhuma entrada sob o corte congelado; ela não deve substituir o C06. O controle C15 mostrou ordenamento retrospectivo melhor que 100 amostras aleatórias pareadas, mas continuou com 11 operações em seis semanas. O C16 testou uma transferência de ativos sem ajustar o score e também não a validou.

A proposta continua útil como sequência de pesquisa e como alerta contra escolher thresholds depois do resultado. A linha C06 deve agora aguardar uma janela temporal futura, com regras congeladas, em vez de nova calibração retrospectiva da janela C16. A proposta não prova que uma estratégia lucrativa exista.

## Artefatos e hashes

- Pré-registro: [`CICLO16_TRANSFERENCIA_C06_BNB_SOL_PROTOCOLO_2026-09-28.md`](CICLO16_TRANSFERENCIA_C06_BNB_SOL_PROTOCOLO_2026-09-28.md), SHA-256 `aff527be58df736d2027b0766c53181934a1a06908c38f4368dc64185dc85ef1`.
- Dataset: `research/data/usdm_c16_bnb_sol_1m/`, SHA-256 `a8b94e27e81c51d1af06896384ec9912edc2e700e8b80eefe2676adab7039393`.
- Manifesto Binance: SHA-256 `515b589acfc361401c70cf266e5a7f026b0a09516f6f3a7b0b567684dc21b349`.
- Relatório máquina: `research/results/cycle16_frozen_c06_transfer_2026-09-28/research.json`, SHA-256 `12066578d153d23f980fbe1358b5b5a3dc4b9ceab3ded0ade6ff5cc43ff74300`.
- Runner executado: hash `ee44fdf44d2e014e85985e2201a7b2d52f65bd3f4b43f79047a1f29518d9d0bd`; arquivo temporário removido após a execução.
- Todos os dez hashes de CSVs estão no `output_sha256` do relatório e foram verificados.
- Fontes primárias de mercado: arquivos públicos oficiais Binance Vision e [documentação de dados de mercado Binance USD-M](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
