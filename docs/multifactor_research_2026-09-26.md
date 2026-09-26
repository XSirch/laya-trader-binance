# Confluência de indicadores: JEV pontua, script decide

Data: 26/09/2026. **Replay executado; nenhuma combinação aprovada como estratégia consistente.**

## Contrato confirmado com o usuário

O usuário autorizou até **US$ 2** para este replay, determinou que todos os indicadores fossem enviados juntos e esclareceu: “quem decide ou nao é nosso script, o jev só retorna o quanto esta dentro do criterio”.

A implementação segue esse contrato: **uma chamada por ativo e instante**, com todos os indicadores e cinco perguntas `noul` no mesmo corpo. O JEV retorna somente probabilidades de aderência aos critérios. Não retorna ordens, compras, vendas nem uma alocação escolhida por ele. O script converte as pontuações em exposição desejada, usando limites fixos. Nenhuma ordem real foi enviada.

## Dados e indicadores enviados juntos

Cada chamada contém **103 campos de mercado**: 50 no período diário, 50 no período de quatro horas e três de contexto entre ativos. Esses campos não representam 103 fontes independentes de informação; vários são transformações correlacionadas do mesmo preço e volume.

| Grupo | Indicadores e dados disponíveis |
|---|---|
| Tendência | Distância de SMA10/20/50/100/200, EMA12/26/50/200, inclinação da SMA50, ADX14 e DI+/DI- |
| Momentum | Retornos de 1/7/30/90 candles, RSI14, MACD, histograma MACD e estocástico |
| Volatilidade | ATR14, volatilidade realizada, posição e largura de Bollinger, queda desde a máxima de 60 candles |
| Participação | Volume relativo, escore de volume, variação de OBV, volume comprador agressor, VWAP, volume financeiro e número de negócios |
| Estrutura | Distância de máximas/mínimas anteriores, posição do fechamento no candle, Fibonacci de 60 e 180 candles |
| Contexto | Força relativa de 30 dias contra BTC, distância de BTC da SMA200 e proporção do universo acima da SMA200 |

Fibonacci usa exclusivamente a máxima e a mínima da janela passada, os níveis 23,6%, 38,2%, 50%, 61,8% e 78,6%, e a ordem temporal dos extremos. Não usa pivôs identificados com candles futuros. O sinal explicita se a máxima veio depois da mínima.

Volume financeiro, número de negócios e volume comprador agressor já existiam nos arquivos Binance, mas não eram lidos pelo modelo de dados anterior; agora são preservados e agregados. Livro de ofertas, spread, interesse em aberto, funding, notícias e dados on-chain **não estão disponíveis neste conjunto** e aparecem explicitamente como ausentes.

## Critérios e decisão local

O JEV recebe cinco critérios fixos, com condições numéricas descritas integralmente no [código](../src/jev_trader/multifactor.py) e na [evidência JSON](multifactor_research_2026-09-26.json):

1. Tendência: pelo menos três confirmações entre médias, inclinação, DI, EMA de quatro horas e ADX.
2. Timing: pelo menos três confirmações entre MACD diário e de quatro horas, faixa de RSI, estocástico e retorno recente.
3. Participação: pelo menos três confirmações entre OBV, compras agressoras, volume relativo, VWAP e força relativa.
4. Estrutura: uma alternativa de recuo em Fibonacci, rompimento com volume ou retomada perto da SMA50.
5. Risco: cumprimento conjunto de limites para ATR, Bollinger, queda diária, volatilidade e distância da máxima recente.

O script aceita exposição comprada somente quando `tendência >= 0,70`, `risco >= 0,75` e pelo menos dois dos três grupos restantes têm aderência `>= 0,65`. Caso contrário, determina caixa. A mudança de caixa para comprado representa entrada; a mudança inversa representa saída; exposição igual mantém a posição. Essas probabilidades representam aderência, **não probabilidade de lucro**.

Os critérios foram fixados antes das 332 consultas. Não foram alterados após conhecer o resultado do replay. O cálculo numérico direto dos mesmos critérios funciona como referência para verificar a interpretação do modelo.

## Execução, custo e velocidade

Foram avaliados BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, com candles diários e de quatro horas já completos. A decisão é semanal, após o fechamento UTC de domingo, e a execução simulada ocorre na abertura seguinte. Cada parcela começa com 25% do capital; permanece comprada ou em caixa até a próxima decisão. O replay cobre janeiro/2025–julho/2026, com custo conservador de 0,25% por lado e custo-base de 0,15% por lado.

O cache contém **332 chamadas completas** ao snapshot `typesafe/jev-1.13-20260917`, com **US$ 0,04351515** de custo total, abaixo dos US$ 2 autorizados. Cada chamada respondeu às cinco perguntas juntas. Houve até quatro chamadas independentes simultâneas, cada uma com o conjunto completo de um ativo/instante; nenhum indicador foi separado em outra chamada.

- Latência mediana: **0,548 s**.
- Percentil 95: **0,685 s**.
- Maior latência: **1,266 s**.

Esses tempos incluem rede e provedor. São medidas de inferência desta execução; não provam viabilidade ou lucro em alta frequência. O controle local reserva US$ 0,01 por requisição em andamento, substitui a reserva pelo custo reportado e impede novas tentativas automáticas de chamadas sem reconciliação. Durante a execução, a soma de custos e reservas foi maior que o custo final.

## Resultados após custos conservadores

| Combinação | 2025 H1 | 2025 H2 | Jan–jul/2026 | Combinado | Entradas combinadas |
|---|---:|---:|---:|---:|---:|
| Tendência + timing + volume | +0,47% | -6,72% | 0,00% | -6,25% | 4 |
| Tendência + Fibonacci + confirmação | 0,00% | +1,73% | 0,00% | +1,73% | 1 |
| Rompimento + volume + força relativa | 0,00% | -2,22% | 0,00% | -2,22% | 2 |
| Combinação por regime | +1,24% | -0,53% | +0,65% | +1,38% | 17 |
| Cinco critérios calculados diretamente | -5,69% | +22,74% | -12,34% | +1,22% | 38 |
| Script com aderências do JEV | -0,83% | +1,62% | -8,70% | **-7,99%** | 25 |

O script com JEV ficou em -6,81% no custo-base. No conservador, teve sete meses positivos de 19 e drawdown de 15,40% nas aberturas diárias, ou **16,20%** quando a mesma posição foi reavaliada nas aberturas horárias. Os 35 instantes em que o script desejou posição comprada não equivalem a 35 entradas, pois decisões consecutivas podem manter a mesma posição.

O resultado positivo do Fibonacci corresponde a **uma única entrada**, evidência insuficiente de consistência. Nenhuma combinação passou pelos critérios já existentes de retorno, frequência, meses positivos e drawdown nas três janelas.

## Aderência e divergências

As pontuações do JEV levaram o script a uma exposição diferente da referência numérica em **52 de 332 decisões**. Comparando cada probabilidade com 0,50 apenas para auditar a classificação do critério, houve:

| Critério | Divergências em 332 avaliações |
|---|---:|
| Tendência | 24 |
| Timing | 24 |
| Participação | 48 |
| Estrutura | 2 |
| Risco | 21 |

Esse diagnóstico distingue duas questões: o JEV nem sempre classificou corretamente as condições explícitas; e o cálculo exato dessas condições também não produziu uma estratégia consistente. Rapidez de inferência e quantidade de indicadores não bastam para demonstrar vantagem financeira.

## Evidência e reprodução

A [evidência integral](multifactor_research_2026-09-26.json) registra perguntas, limites do script, métricas por janela, robustez a custos e atraso, exclusão de ativos, hashes e auditoria individual das 332 respostas. Os estados completos podem ser regenerados dos arquivos verificados e ficam em `results/multifactor_events.jsonl`. O cache com reservas e respostas está em `results/jev_multifactor_decisions.jsonl`.

```powershell
uv run python -m unittest discover -s tests -v
uv run python -m jev_trader.multifactor
uv run python scripts/check_encoding.py
```

O comando acima reutiliza o cache e não inicia chamadas pagas. Para o replay autorizado nesta sessão foi usado `--budget-usd 2`. Resultados ausentes não são inventados: se o cache estiver incompleto e novas chamadas não estiverem habilitadas, o relatório marca `jev_complete=false` e omite o resultado JEV completo.

O histórico já foi examinado por pesquisas anteriores. Este é um estudo exploratório, sem validação prospectiva intocada. O modelo também pode ter encontrado esse histórico em seu treinamento; retirar nome do ativo e datas da entrada reduz pistas, mas não elimina essa possibilidade. Candles não provam preços executáveis e o universo fixo pode introduzir viés de seleção.

Fontes primárias: [formato dos dados Binance e checksums](https://github.com/binance/binance-public-data/blob/master/README.md) e [API JEV, múltiplas perguntas na mesma chamada e significado de Noul](https://openrouter.ai/blog/insights/what-is-jev/).
