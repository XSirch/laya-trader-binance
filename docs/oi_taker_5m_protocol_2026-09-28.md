# Protocolo: continuação intradiária com open interest e fluxo taker

## Hipótese e relação com testes anteriores

Hipótese única para BTCUSDT perpétuo: quando o preço anda pelo menos 0,30% em 60 minutos, o open interest cresce ao menos 0,10% no mesmo intervalo e o fluxo taker de 60 minutos acompanha a direção, a continuação pode ter chance maior de atingir um alvo fixo antes do stop. Um HGB filtra entradas por probabilidade estimada de vitória. Estudos anteriores testaram fluxo/retorno em barras curtas e posicionamento OI semanal; não testaram OI intradiário de cinco minutos junto com a regra de saída abaixo. A hipótese continua sujeita a seleção de múltiplas estratégias e não será considerada comprovada.

O experimento reutiliza apenas futuros de cripto, sem ETFs, chamadas JEV ou ordens reais. Uma consulta inicial de schema e duas linhas confirmou conectividade; nenhum desempenho de operação foi lido antes deste protocolo.

## Fonte, corte e alinhamento

Fonte oficial: API pública Binance USDⓈ-M para candles `GET /fapi/v1/klines`, OI `GET /futures/data/openInterestHist` e volume taker `GET /futures/data/takerlongshortRatio`, todos em `5m`, BTCUSDT perpétuo. A Binance limita o histórico de OI e taker a 30 dias. Janela congelada pelo relógio do servidor consultado em 2026-09-28: início `2026-08-29T00:55:00Z` (1787964900000) e fim exclusivo `2026-09-28T00:55:00Z` (1790556900000). Treino é os primeiros 20 dias; validação é os 10 dias finais, a partir de `2026-09-18T00:55:00Z` (1789692900000). O timestamp do servidor que fixou esta janela foi `1790557086063` (2026-09-28T00:58:06.063Z). A captura parcial inicial não chegou à análise; os bytes foram preservados, a paginação mais recente primeiro para OI/taker foi confirmada, e o corte foi realinhado à retenção de 30 dias antes de calcular resultados. Não avançar, encurtar ou mudar a janela após ver resultados.

- Salvar respostas brutas, timestamps de consulta, parâmetros, status HTTP e hashes antes da análise. OI/taker são paginados de trás para frente porque a resposta limitada entrega os registros mais recentes; candles são paginados para frente. Ordenar por timestamp antes do alinhamento.
- Open interest usa o timestamp documentado como fim do período; taker usa início do período; candle usa horário de abertura. OI em `t+5m` e taker em `t` são associados ao candle que abriu em `t` e fechou em `t+5m`.
- O sinal é calculado só após candle, OI e volume estarem completos. O replay entra na abertura de `t+10m`, um candle adicional após o fechamento, para modelar o atraso observado na publicação do dado.
- Descartar até doze candles iniciais apenas como aquecimento dos indicadores. Barras ausentes, desalinhadas, duplicadas ou com OHLC/volume inválidos depois do aquecimento quebram a continuidade; não interpolar. Cortar a validação antes de qualquer operação cuja saída não esteja integralmente observável antes do fim.
- Histórico baixado hoje não prova a hora em que a estatística foi publicada originalmente. A janela já se sobrepõe a resultados de outras pesquisas; é uma triagem intramês, não um holdout temporal totalmente inédito.

- Paginação reversa: usar o menor timestamp retornado como o próximo `endTime`; subtrair 1 ms pula uma barra de 5m no taker. No OI, remover somente sobreposições de borda com registros idênticos e rejeitar duplicatas conflitantes. Linhas fora do intervalo congelado são excluídas; tolerar no máximo uma barra extra na borda inferior da resposta.

## Sinal de entrada e rótulo

A cada candle 5m, direction é o sinal do retorno `close[t]/close[t-12]-1`. Só há candidato se o módulo do retorno de 60m for `>=0,003`, OI de 60m subir `>=0,001`, e o taker buy fraction ponderado por volume nos últimos 12 candles acompanhar a direção (`>=0,53` em long; `<=0,47` em short). Todos os cortes estão congelados. Features adicionais do modelo: retorno de 15m, retorno de 60m, OI de 60m, fração taker compradora de 60m, ATR14 como fração do fechamento, posição do fechamento no candle e log do volume cotado contra a média móvel anterior de 12 candles. Usar apenas candles completos até `t`; sem símbolo ou timestamp no vetor.

A entrada é na abertura de `t+10m`. ATR14 usa a informação fechada no sinal. Stop fica a `1,0 x ATR` contra a posição e alvo a `1,3 x ATR` a favor. Duração máxima é seis candles (30 minutos) após a entrada. Precedência em gap: stop no open se o gap ultrapassar o stop; alvo limitado ao preço-alvo; se stop e alvo forem tocados no mesmo candle, contar stop primeiro. No timeout, sair no fechamento do sexto candle. Taxa e slippage juntos são modelados como custo de 0,10% por lado no cenário-base e 0,15% no estressado. Funding histórico é debitado/crédito quando o horário de saída cruza uma liquidação; nenhuma posição é alavancada. PnL líquido positivo define vitória.

## Modelo, execução e gates

Treinar somente com candidatos cujo rótulo esteja completamente encerrado antes do início da validação. A primeira metade da janela pode gerar rótulos sobrepostos de cinco em cinco minutos; essa dependência temporal será declarada e os resultados não serão tratados como centenas de operações independentes. Modelo fixo: `HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=40, l2_regularization=10, early_stopping=False, random_state=2026)`. Exigir 500 linhas rotuladas e ambas as classes; se não houver dados suficientes, o modelo não opera. Não calibrar probabilidade nem procurar grade de modelos, features, limiares ou stops. Entrada do filtro só com `P(vitória)>=0,70`.

Na validação, no máximo uma posição por vez; após a entrada, ignorar sinais até a saída. Comparar filtro HGB com a mesma regra-base sem ML, no mesmo período e custos. Notional máximo de 100% do patrimônio, sem alavancagem, com capital composto. Calcular acerto, payoff líquido, EV líquido por operação sobre notional inicial, retorno da carteira, drawdown marcado a cada candle e limite adverso intratrade. Gatilhos de aprovação: acerto `>=70%`, payoff `>=1:1`, EV `>1,2%`, drawdown `<=10%` e ao menos 30 operações completas de validação, todos sob custo estressado; no cenário-base, o acerto também deve ser pelo menos 65%. Resultado positivo neste mês exige período prospectivo congelado antes de qualquer uso real.

## Proveniência e limite temporal

O executor registra SHA-256 do protocolo, código e respostas. Respostas ausentes ou dados não alinhados interrompem o replay. A extração pode ser repetida somente com os mesmos timestamps/arquivos; não substituir conteúdo no lugar. Nenhuma chamada paga ao JEV, ordem ou credencial de conta é permitida.

Fontes oficiais consultadas: https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data e https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market .
