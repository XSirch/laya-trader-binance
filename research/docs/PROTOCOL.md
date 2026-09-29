# Protocolo técnico e limites — v0.1

> Direção atual: implementar e melhorar a base numérica/determinística primeiro;
> Laya/Jev somente em experimento posterior de valor incremental. Ver
> `HANDOFF_LOCAL.md`, revisão documental 2. Esta revisão não altera o código,
> os custos, os limiares ou as regras técnicas descritas abaixo.

## Contrato do sinal

Um candidato contém mercado, símbolo, estratégia, direção, instante do candle fechado,
ATR conhecido, stop/alvo/trailing, horizonte máximo e 66 entradas numéricas. Não contém
preço futuro, resultado do trade ou rótulo como entrada do estimador. A identidade da
estratégia é one-hot. Spot e USD-M têm modelos e séries de preços separados.

A ação de entrada só é elegível depois de estratégia + probabilidade calibrada + retorno
esperado. A ação ABSTAIN é explícita. A regra de regime inicial é determinística;
não há alegação de regime aprendido por rede neural. Riscos e saídas não dependem de
um LLM. Em Spot uma venda só encerra inventário; em futuros há entrada long/short e
fechamento da direção correspondente. Reversão instantânea e hedge mode não fazem
parte desta implementação.

## Auditoria causal

Informação do candle i só está disponível no seu fechamento. A entrada ocorre em i+1.
Indicadores de prazos maiores só são alinhados a partir do fechamento real daquele
prazo. Donchian e âncoras Fibonacci excluem o candle corrente quando necessário para
comparar com níveis anteriores. Não há bfill, centered rolling ou ZigZag retrospectivo.

Os testes verificam invariância por prefixo: acrescentar candles futuros não pode
reescrever features/sinais anteriores. Outro teste altera todo o trecho posterior
à fronteira de seleção e exige previsões de modelos treinados idênticas.

Rótulos representam o PnL do caminho inteiro até stop/alvo/trailing/expiração, com
custos e funding. Não são apenas o sinal da variação do candle seguinte. Eventos
censurados não viram vitórias. Janelas próximas às fronteiras são purgadas; o embargo
mínimo de 480 minutos cobre o maior horizonte. Na avaliação é proibida nova entrada
nos últimos 480 minutos por uma regra fixa, independente do resultado futuro do trade.

Não há otimização com o conjunto final. Calibração de probabilidades usa uma janela
posterior ao treino. Seleção de limiar usa outra janela posterior. Após seleção,
modelo, custo e threshold ficam congelados para evaluate. O relatório de calibração
avisa que suas métricas ajustadas são calculadas no conjunto usado para ajustar o
calibrador, portanto não são desempenho independente.

## Custos e execução

As taxas são aplicadas à entrada e à saída, com os respectivos nocionais. Slippage
adverso é aplicado em cada preenchimento. É uma hipótese fixa de execução, não uma
reconstrução do book. Não há maker fills presumidos, fila de ordens ou rebates fictícios.

O backtest usa OHLC de negócio para stop/alvo. Mark price é utilizado para marcação
a mercado de USD-M e limites conservadores no débito/crédito de funding. Não misturar
esse modelo com stop por MARK_PRICE em produção sem repetir a validação correspondente.

O trailing do protótipo tem distância constante em R, baseada no ATR da entrada, e
ratchet ao fechar o minuto. Trailing percentual nativo é outro algoritmo. Traduzir
ATR/R para trailingDelta/callbackRate altera a execução e exige novo experimento.

Posições simultâneas entre ativos de um modelo são proibidas nesta primeira versão.
Modelos Spot e USD-M executados separadamente NÃO compartilham uma trava global de
capital. A futura camada de carteira precisa consolidá-los antes de produção.

## Aceitação e overfitting

70% é meta, não propriedade garantida de um estimador. A grade de thresholds deve ser
registrada antes de observar a seleção. A análise por estratégia/regime e a comparação
com regras sem ML são diagnósticas. Retirar estratégias depois de olhar o teste contamina
essa janela: exige outro experimento e nova amostra realmente reservada.

A reamostragem semanal do win rate é uma aproximação e não resolve seleção de modelos,
regimes novos, survivorship bias ou dependência que dure mais de uma semana. Se o
universo for escolhido depois de ver a rentabilidade de seus ativos, registrá-lo como
exploratório. Não anunciar que dois ativos representam todas as criptomoedas da Binance.

Os períodos de 2025–2026 já apareceram nas pesquisas existentes do projeto. Não podem
ser rebatizados como pristine holdout apenas porque este módulo foi escrito depois.
Todo experimento deve registrar períodos já vistos, tentativas, parâmetros e hashes.

## Limitações deliberadas

Sem ordens reais, integração REST autenticada, WebSocket, testnet, partial fills,
reconciliação, lucro comprovado ou pesos financeiros treinados nesta entrega.
Sem alavancagem acima de 1x, margem/ADL/liquidação detalhados ou renda esperada prometida.
Sem dados sintéticos misturados ao histórico real. Os dados artificiais existem
somente em tests/ e nunca são oferecidos como dataset de investimento.
