# Família técnica completa: protocolo antes dos resultados

Depois do resultado negativo dos modelos econômicos, será testada uma família separada com todos os campos numéricos e booleanos retornados por `market_state.states` nos candles diários, junto dos dez fatores econômicos da rodada anterior. Isso inclui distâncias de médias, RSI, MACD, ADX/DI, Bollinger, ATR, volume, fluxo, estrutura e níveis de Fibonacci. Valores ausentes não serão inventados; a observação deverá ser considerada indisponível.

Permanecem as penalidades ridge 0,1/1/10, a janela móvel de 104 semanas, mínimo de 52 semanas completas e purga do alvo ainda não encerrado. Permanecem os percentis com empates, as duas formas de dimensionamento, hedge de beta, exposição bruta de 50%, custos por lado de 0,10%/0,15%/0,30% e execução principal às 01:00 UTC. A referência é previsão zero/caixa.

Seleção somente pelo desenvolvimento até 2023. Reportar todas as variantes, erros de previsão, períodos completos e falhas de execução. Os resultados até setembro de 2026 já foram examinados em outras famílias e serão identificados como retrospectivos. Não atribuir independência estatística a uma nova combinação de indicadores no mesmo histórico.

Este protocolo não altera os resultados anteriores nem afirma que o experimento já foi executado. O JEV, caso usado em etapa posterior, receberá os indicadores em uma chamada por avaliação e apenas pontuará aderência; a decisão continua pertencendo ao script.
