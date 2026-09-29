# Avaliação inicial: GainzAlgo V2 Alpha

## O que está documentado

Na página oficial consultada em 27/09/2026, GainzAlgo V2 é apresentado como um indicador pago para TradingView, ativado com o nome de usuário da plataforma, com sinais BUY/SELL e níveis de take-profit e stop-loss integrados. A página oferece o preset Alpha e o recomenda para intervalos menores, de 1 minuto a 1 hora; também o chama de "AI-powered" e afirma que não repinta e não tem atraso. Essas são descrições e alegações do vendedor, não resultados verificados independentemente; a página não publica modelo, dados de treino, código ou regra completa que permita conferir as afirmações de IA e de não repintura.

Outras páginas do próprio fornecedor citam, em termos gerais, momentum, pressão de volume, volatilidade, tendência em vários timeframes, níveis dinâmicos de suporte/resistência a partir de estrutura de preço e clusters de volume, e zonas de SL/TP calibradas pela volatilidade/ATR. Elas não indicam fórmulas, janelas, pesos, critérios de confirmação ou política de execução. Uma página promocional deixa métricas como usuários e sinais por dia como “Insert real number”, portanto não a trato como validação quantitativa. Fontes: [artigo V2 sobre sinais](https://gainzalgo.com/blogs/trading/gainzalgo-v2-smarter-trading-better-results), [descrição de recursos do algoritmo](https://gainzalgo.com/best-trading-algorithm), [artigo Alpha](https://gainzalgo.com/gainzalgo-v2-alpha-trading-indicator).

A página pública não explica a regra de sinal, os parâmetros do preset Alpha, como os níveis de TP/SL são calculados, em que momento um sinal se torna definitivo, nem fornece uma série legível e completa de sinais com timestamp e fills. As imagens e os exemplos de backtest publicados pelo vendedor não bastam para reconstruir um teste independente com custos, latência, stop/target e conflitos intrabar.

## Decisão de pesquisa

GainzAlgo V2 Alpha fica registrado como hipótese pendente de dados reproduzíveis. O usuário informou que não tem acesso ao indicador e pediu uma implementação semelhante no projeto. Portanto, o próximo experimento será uma estratégia independente de ação de preço com confirmação de sweep/reclaim, contexto multitemporal, volume e barreiras de saída. Isso usa somente a categoria de ideias que o fornecedor descreve publicamente; não copia nem representa a regra privada do GainzAlgo. Não vou reconstruir o indicador a partir de imagens.

Para avaliar no escopo atual, o conjunto mínimo é um CSV exportado do histórico de alertas do TradingView ou um log de webhook, sem omitir alertas perdedores, acompanhado da configuração exata do preset. Uma linha por evento deve conter:

| Campo | Conteúdo necessário |
| --- | --- |
| `signal_time_utc` | Timestamp da emissão do sinal, em UTC, com precisão disponível |
| `bar_close_time_utc` | Fechamento do candle que confirmou o sinal; indicar se o alerta ocorreu intrabar |
| `exchange`, `symbol`, `market_type` | Mercado e ativo exatos, por exemplo Binance Spot `BTCUSDT` |
| `timeframe`, `preset`, `version` | Intervalo, Alpha e versão/configuração visível do indicador |
| `direction` | BUY ou SELL conforme o alerta original; registrar se SELL significa encerrar Spot ou abrir posição short |
| `entry`, `stop_loss`, `take_profit` | Níveis mostrados quando o sinal foi emitido, sem recalculá-los depois |
| `alert_id` | Identificador ou texto original para deduplicar sem apagar sinais válidos |

Também é necessário informar se o backtest é Spot long/cash ou futuros long/short, as taxas efetivas por lado, slippage e regra de preenchimento. Imagens isoladas ou apenas os trades vencedores não permitem inferir performance.

## Protocolo que será aplicado quando houver sinais

1. Congelar os arquivos originais, a configuração Alpha e seus SHA-256 antes de examinar o resultado agregado.
2. Verificar duplicatas, horários, sinais intrabar, cobertura de todos os períodos e consistência entre alerta e candle. Preservar todos os sinais, inclusive perdas.
3. Alinhar ao histórico de candles do mesmo mercado e timeframe. Se stop e alvo forem ambos tocados dentro do mesmo candle e não houver dados menores que revelem a ordem, contabilizar primeiro o stop.
4. Aplicar taxa, spread/slippage e atraso na entrada e saída; reportar casos de gap em stop, posição sobreposta e sinal oposto. No replay Spot, SELL não será contado como posição short sem uma regra e um mercado de margem/futuros explicitamente autorizados. Separar desenvolvimento de um holdout temporal ainda não consultado.
5. Reportar retorno líquido, drawdown observado e adverso, exposição, giro, número de operações, expectativa por trade e resultados por ano/regime. Para a pesquisa ativa, o gate conjunto é acerto líquido de aproximadamente 70%, payoff >=1:1 (ideal 1,2–1,5), EV líquido >1,2% por trade e drawdown de conta <=10%, em custos base e estresse.

O indicador é anunciado para vários mercados, mas o escopo do usuário está limitado a pares de cripto Spot ou futuros, sem ETFs ou outros produtos. A pesquisa atual usa Binance USD-M futures de um minuto; a aproximação histórica de GainzAlgo foi testada em Binance Spot horário e não representa o preset Alpha. Uma avaliação direta exige exportação de sinais correspondente ao mercado, par e timeframe selecionados.

## Implementação independente em andamento

O protocolo [price_action_alpha_protocol_2026-09-27.md](price_action_alpha_protocol_2026-09-27.md) congelou um detector de sweep/reclaim de mínima de 24 horas e um HGB que estima o retorno bruto em unidades de risco. As saídas usam stop sob a mínima do candle de sinal, alvo de 2R e limite de 24 horas. Nos arquivos históricos existentes, o ML selecionou 106 entradas a 0,15% por lado e 42 a 0,30%, mas ambas as carteiras perderam (-14,45% e -10,80% acumulados). Pela avaliação por operação, os acertos foram 32,1%/23,8% e os EVs -0,583%/-1,080%. A família foi rejeitada e o resultado completo está em [price_action_alpha_research_2026-09-27.md](price_action_alpha_research_2026-09-27.md). É uma aproximação transparente de categorias gerais divulgadas pelo fornecedor, feita sobre Binance Spot horário; não é o GainzAlgo V2 Alpha e não confirma suas alegações.
