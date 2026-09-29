# CICLO 02 — pré-registro dos candidatos

Registrado em 28/09/2026, antes de treinar ou avaliar estas variantes. As combinações abaixo são hipóteses de pesquisa. Nenhuma está aprovada para operação.

## Universo, relógio e execução

- Somente BTCUSDT e ETHUSDT em Binance Spot e USD-M perpétuo; Spot aceita somente posições compradas. Cada mercado é avaliado separadamente, sem somar folds, modelos, custos ou mercados para atingir gates.
- Candles UTC de 1 minuto formam candles de 15 minutos, 1 hora e 4 horas. Cada decisão usa apenas candles completos; o contexto horário precisa ter fechado até o instante da decisão.
- Entrada simulada na próxima abertura disponível de 1 minuto depois do fechamento do sinal de 15 minutos. Stops e proteção são verificados a cada minuto. Se stop e alvo forem ambos tocados no mesmo minuto, assume-se stop primeiro.
- Um único trade global por mercado fica aberto de cada vez. O resultado Spot não é combinado com USD-M. Sem ordens reais.
- Features elegíveis: preço, volume, ATR, RSI, EMA e estrutura dos candles fornecidos. Não incluir ETFs, outros instrumentos, dados sintéticos, nem campos externos sem recibos verificáveis.

## Definições congeladas das famílias

O contexto direcional é simétrico. Para compra, o último candle completo de 1h e o último de 4h fecham acima da EMA200, e a EMA200 em ambos está acima do valor de cinco candles completos antes. Para venda em USD-M, os sinais se invertem.

- Retomada de tendência: com contexto alinhado, o último candle completo de 15m cruza de volta a EMA21 na direção do contexto: lado × (fechamento − EMA21) > 0 e o valor do candle anterior ≤ 0.
- Rompimento/continuação: com o mesmo contexto, o fechamento completo de 15m supera a máxima dos 20 candles anteriores para compra ou fica abaixo da mínima dos 20 anteriores para venda, e o volume do candle de sinal é ≥1,3× a mediana do volume dos 20 candles anteriores.

ATR de referência é o ATR(14) dos candles completos de 15m no instante do sinal. Repetições da mesma família, ativo e direção têm cooldown de um candle de 15m. Não há reentrada enquanto a posição global do mercado estiver aberta.

## Grade registrada: 12 variantes por mercado

Cada uma das 12 linhas é executada separadamente em Spot e USD-M. As duas famílias × dois tempos máximos × três saídas totalizam exatamente 12 variantes por mercado. Regras, HGB e XGBoost CUDA são comparadores de seleção sobre os mesmos candidatos, não variantes adicionais.

| ID-base | Família | Tempo máximo | Saída |
|---|---|---:|---|
| TR-6H-FIX | Retomada de tendência | 6h | Stop inicial 1 ATR; alvo 1,5R |
| TR-6H-TRAIL | Retomada de tendência | 6h | Stop inicial 1 ATR; trailing ativa em +1R e fica 1 ATR atrás; sem alvo fixo |
| TR-6H-TREND | Retomada de tendência | 6h | Stop rígido 1 ATR; sai no primeiro fechamento de 15m contra a EMA21 |
| TR-24H-FIX | Retomada de tendência | 24h | Stop inicial 1 ATR; alvo 1,5R |
| TR-24H-TRAIL | Retomada de tendência | 24h | Stop inicial 1 ATR; trailing ativa em +1R e fica 1 ATR atrás; sem alvo fixo |
| TR-24H-TREND | Retomada de tendência | 24h | Stop rígido 1 ATR; sai no primeiro fechamento de 15m contra a EMA21 |
| BO-6H-FIX | Rompimento/continuação | 6h | Stop inicial 1 ATR; alvo 1,5R |
| BO-6H-TRAIL | Rompimento/continuação | 6h | Stop inicial 1 ATR; trailing ativa em +1R e fica 1 ATR atrás; sem alvo fixo |
| BO-6H-TREND | Rompimento/continuação | 6h | Stop rígido 1 ATR; sai no primeiro fechamento de 15m contra a EMA21 |
| BO-24H-FIX | Rompimento/continuação | 24h | Stop inicial 1 ATR; alvo 1,5R |
| BO-24H-TRAIL | Rompimento/continuação | 24h | Stop inicial 1 ATR; trailing ativa em +1R e fica 1 ATR atrás; sem alvo fixo |
| BO-24H-TREND | Rompimento/continuação | 24h | Stop rígido 1 ATR; sai no primeiro fechamento de 15m contra a EMA21 |

O tempo máximo é saída obrigatória ao fim de 6h ou 24h. Toda saída usa preço e custos conservadores do simulador. Stop, alvo e trailing são recalculados a partir do fill real simulado, nunca do close usado para sinal.

## Estudos próximos já revistos

Estes resultados são negativos ou insuficientes e não serão reexecutados com os mesmos sinais, features, limiares ou cortes:

- [Sweep/reclaim inspirado no GainzAlgo](../../docs/price_action_alpha_research_2026-09-27.md): HGB sobre varredura/reclaim de mínima de 24h teve EV líquido por trade de −0,583% e −1,080% nos custos reportados. A nova retomada não usa o evento de varredura de 24h; o rompimento usa fechamento de 15m e contexto completo de 1h/4h.
- [Rompimento de faixa de 60m com fluxo](../../docs/futures_range_breakout_research_2026-09-27.md): nenhum threshold selecionou operação na validação e o controle fixo falhou. Não repetiremos o sinal de 60m com fluxo; a hipótese registrada usa rompimento de 20 candles completos de 15m, volume relativo e contexto 1h/4h.
- [Classificador LONG/IDLE/SHORT de 1m](../../docs/minute_ml_buy_idle_sell_research_2026-09-27.md): validação com 209 trades teve acerto e EV negativos nos dois custos. Nesta grade, a direção e os setups vêm de regras explícitas em 15m; ML só filtra candidatos.
- [Reclaim de VWAP/pullback](../../docs/vwap_pullback_research_2026-09-27.md): EV −0,211% e acerto 14,71% na validação; não repetir VWAP ou reotimizar seus thresholds.
- [Short-only de baixa volatilidade](../../docs/low_volatility_short_only_research_2026-09-28.md): foi o sinal histórico mais promissor, mas os recortes de stress tiveram 17 e 22 trades; o combinado teve 39 e foi escolhido depois da leitura do ledger. É evidência exploratória insuficiente, não candidato já aprovado nem parte dos 12 novos desenhos.

A grade abaixo não é declarada independente dos mesmos regimes de mercado: as datas históricas já foram observadas em outros estudos. Sua finalidade é testar a definição multi-timeframe pré-registrada e, depois de congelada, recolher evidência prospectiva sem ajustar os parâmetros.

## Comparadores e prevenção de vazamento

1. Regra sem ML: aceita todo candidato determinístico elegível.
2. HGB em CPU e XGBoost CUDA: somente filtram esses candidatos. Classificador estima a chance de retorno líquido positivo e regressor estima R líquido; nenhum deles inventa direção, entrada ou saída.
3. Jev/Noul não prevê lucro nem escolhe direção nesta grade. Uma checagem separada de aderência pode ser registrada, mas não altera entradas, saídas ou elegibilidade.
4. Threshold de probabilidade: grid fechado de 0,35 a 0,80 em passos de 0,05; piso de retorno esperado: 0,05R. Selecionar no bloco de seleção e congelar. Relatar todas as 12 variantes; escolher apenas entre as que cumprirem os gates.
5. Treino histórico: candles locais verificados de 13/08/2024 até 01/09/2026 exclusivo. Blocos cronológicos: treino até 01/07/2025; calibração de 01/07/2025 a 01/01/2026; seleção de 01/01/2026 a 01/09/2026. Labels só entram quando saída e custos estão disponíveis antes do corte; purga e embargo mínimos de 24h.
6. Esses intervalos são desenvolvimento retrospectivo. Períodos e resultados de estratégias anteriores já foram vistos; não serão descritos como holdout intocado. Após concluir código, treino e seleção, congelar hashes de dados, código, modelos, thresholds, custos e protocolo antes de iniciar paper prospectivo.

## Custos, sizing e critérios

- Spot: taxa configurada de 10 bps por lado; slippage adverso de 5 bps por lado.
- USD-M: taxa configurada de 5 bps por lado; slippage adverso de 5 bps por lado; funding observado é incluído.
- Stress: dobrar taxa e slippage; funding observado permanece. Reportar também ledger pareado com trades e quantidades base fixos.
- Sizing fixo para esta etapa: risco calculado de 0,25% do patrimônio por trade, considerando stop e fricção; notional máximo 1× patrimônio. Sem modelo de liquidação.
- Gate por variante/mercado: EV líquido médio >1,2% do nocional inicial, payoff ≥1,0, profit factor ≥1,25, pelo menos 200 trades completos não duplicados, presença em pelo menos oito semanas ativas e stress integral positivo com payoff ≥1,0.
- Acerto próximo de 70% é preferência, não piso. Drawdown não tem teto; medir e minimizar entre candidatos aprovados. Publicar todos os folds e métricas, inclusive reprovações.

Uma revisão de 7 dias é somente triagem operacional e de evidência inicial, de acordo com a preferência do usuário por ciclos curtos. Ela não aprova uma estratégia nem substitui a amostra, as oito semanas ativas e os gates acima. Se os dados favorecerem algum candidato, estender o paper congelado até cumprir a amostra. Se falhar claramente, interromper aquele candidato sem reajustar usando os mesmos dias.

## Estado deste registro

O P0 dos artefatos anteriores foi completado em 28/09/2026. Ainda falta implementar o motor multi-timeframe e registrar um manifesto de freeze antes do treino. Nenhum dos 12 candidatos foi treinado ou avaliado; não há sinal autorizado para negociação.
