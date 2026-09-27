# Previsão horária direcional com filtro de giro

Consulta: 26/09/2026. Escopo: leitura de fontes e comparação dos protocolos locais; sem nova previsão, backtest, download de mercado ou chamada JEV.

## Síntese da fonte primária

Candles UTC fechados em t alimentam previsão de log(C[t+1]/C[t]); a carteira usa posição_t*(C[t+1]/C[t]−1)−c*|posição_t−posição[t−1]|. Não identifiquei execução posterior ao fechamento, latência ou purga explícitas. Janelas móveis: 12 meses treino, 3 validação, 3 teste; avanço trimestral, seleção Optuna/validação e refit nos 15 meses anteriores ao teste, sem refit horário.

c=0,001 significa 10bps por unidade de giro: entrada+saída=20bps; reversão=20bps. Long-only, λ=2: entra acima de +20bps, sai abaixo de −20bps; dentro da banda mantém posição. Funding não entra. A seleção técnica reduz 94 candidatos a dez por fold, usando treino.

O destaque XGBoost/OHLCV+TA+EGARCH/MSE/loss-best: ARC composto 65,40%, drawdown 67,42%. λ=2 maximiza ARC long-only na grade apresentada; pré-registro independente não é demonstrado. Nos λ>0, drawdowns permanecem entre 62,63% e 76,10%. Somente 16/27 folds são lucrativos; superioridade de Sharpe contra buy-and-hold não fica confirmada estatisticamente. Sensibilidade de custos recalcula posições, usando outro seletor. A agenda começa testes em abril/2019; a origem declarada é USD-M Binance desde dezembro/2017. Lacunas recebem fechamento anterior e volume zero. Código somente mediante solicitação.

Fonte: Bysik e Ślepaczuk, [Machine Learning-Based Bitcoin Trading Under Transaction Costs: Evidence From Walk-Forward Forecasting, arXiv:2606.00060v1](https://arxiv.org/html/2606.00060v1), seções 3.1–4.6, 5.2, 6.1–6.3, 7, tabela 31 e disponibilidade de código. A síntese acima tem 161 palavras por separação em espaços. O texto integral foi acessível; não obtive os dados/código dos autores. Não há solicitação enviada aos autores.

## Verificação independente da origem

A Binance registra o lançamento de Futures em setembro de 2019, no próprio relato institucional [Building Foundations](https://www.binance.com/en/blog/all/419417682154909696), seção Futures. Isso torna a origem declarada no artigo incompatível com uma série integral de contratos USD-M realmente negociados. Falta esclarecer a procedência do trecho anterior ao lançamento. Não presumo substituição por spot: a fonte não a demonstra. Essa inconsistência impede tratar o estudo como réplica auditável a partir da descrição disponível.

## Diferença em relação ao repositório

A hipótese BTC direcional, decidida a cada hora e com retenção da posição enquanto a previsão não justificar o giro, é distinta dos dois estudos locais abaixo. Essa classificação descreve alvo e política; não é evidência de rentabilidade.

| Implementação local | Relógio e alvo preservados | Decisão existente |
| --- | --- | --- |
| [tree_prediction.py](../src/jev_trader/tree_prediction.py), funções `_week_label` e `build_forecasts`; [protocolo](tree_prediction_protocol_2026-09-26.md) | Segunda 00h; retorno entre aberturas de 01h, por sete dias, relativo à média transversal; treino expansivo e refit mensal. | Quintis comprados/vendidos, hedge de beta em BTC; rebalanceamento semanal e filtro de custo, sem regra adicional de retenção para economizar giro. |
| [funding_event_prediction.py](../src/jev_trader/funding_event_prediction.py), funções `_daily_label` e `build_forecasts`; [protocolo](funding_event_protocol_2026-09-26.md) | Evento próximo de 00h; decisão 01h, execução 02h; retorno do par com hedge BTC durante 24h; treino expansivo e refit mensal. | Até três pares; decisão diária condicionada ao funding realizado e ao custo. Compensa quantidades e pode manter posições entre dias. |

O [market_state.py](../src/jev_trader/market_state.py), função `states`, já calcula médias, RSI, MACD, ADX/DI, Bollinger, ATR, volume/fluxo e Fibonacci a partir de candles. Isso fornece componentes reutilizáveis; não comprova que os snapshots diários existentes sejam indicadores horários. O [protocolo técnico anterior](broad_technical_prediction_protocol_2026-09-26.md) declara candles diários e horizonte semanal.

## Lacunas para uma investigação local própria

Estas são inferências de desenho da pesquisa, não especificações atribuídas aos autores:

- Definir explicitamente fechamento observado, tempo de decisão e primeira abertura executável. Construir o alvo com os mesmos extremos da execução e aceitar no treino apenas rótulos encerrados antes do ajuste. Os dois preditores locais já verificam `label_end_ms < cutoff/decision`; preservar essa propriedade.
- Reconstruir os indicadores no relógio escolhido, com continuidade e aquecimento suficientes. Não preencher candles sem negócios para simular execução e não chamar um pacote diário de informação horária.
- Escolher instrumento e período com procedência verificável. Uma investigação spot precisará da contabilidade de caixa e quantidades spot; uma investigação em perp precisará de funding efetivo e margem. O executor de pares/basis não demonstra automaticamente a contabilidade de BTC long-only.
- Persistir posição entre decisões e entre janelas de avaliação, cobrando apenas giro efetivo, entrada inicial e saída terminal. Uma previsão pequena de sinal oposto não deve virar saída se a política congelada especificar uma banda de retenção.
- Congelar modelo, variáveis, agenda, custos, regra de giro e tratamento de risco antes dos resultados. Não escolher limiares locais por proximidade ao retorno destacado na literatura. Manter a meta de CAGR líquido de 50% e drawdown de 10%, incluindo o limite adverso intrahorário já exigido pelos protocolos locais.
- Apresentar todas as variantes previstas e reconhecer que o histórico local já foi pesquisado. A distinção da hipótese não restaura independência da amostra. Confirmar a meta exige evidência local de execução e risco, seguida de avaliação prospectiva.

Esta nota motiva uma hipótese testável. A evidência consultada não demonstra o par retorno/risco solicitado, e as lacunas de origem e execução precisam permanecer visíveis.

