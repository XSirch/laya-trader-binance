# Protocolo: sentimento como dado adicional para sizing de cauda

## Hipótese e escopo

O teste anterior de risco de cauda, com previsões semanais do quantil 10%, reduziu o drawdown em relação a comprar e manter, mas perdeu 1,57% líquido no holdout de 2025 em diante e não atingiu a meta de retorno/drawdown. Não será retunado. A hipótese nova é que o Crypto Fear & Greed Index (FGI), que inclui atenção e sentimento além de preço/volatilidade, acrescente informação ao mesmo alvo de risco.

Este é um teste de ablação de uma entrada de dados nova, não uma reprodução do GainzAlgo V2 Alpha e não uma estratégia direcional baseada em comprar medo ou vender ganância. O FGI mede sentimento agregado de Bitcoin e não é específico de cada altcoin. O resultado continua retrospectivo e exploratório.

## Dados e disponibilidade

- Baixar uma vez `https://api.alternative.me/fng/?limit=0&format=json`; preservar o payload em `.cache/macro_fgi/fng.json`, fora do Git, e registrar SHA-256, quantidade, intervalo e timestamps usados.
- Validar estrutura, timestamps únicos e crescentes após ordenação, valores inteiros de 0 a 100 e ausência de datas futuras em cada decisão.
- A API fornece a série histórica atual, sem vintages históricas imutáveis. O atraso abaixo reduz risco de usar o valor antes da publicação diária, mas não elimina revisões retrospectivas do fornecedor. Tratar qualquer vantagem observada como sujeita a esse limite.
- O fornecedor informa que o índice combina volatilidade e momentum/volume com redes sociais, dominância e buscas. Parte das entradas é correlacionada com variáveis já presentes no modelo.

## Features e alinhamento temporal

- Mercado, candles, semanas UTC, rótulo semanal, períodos, treino, modelo base e sizing são exatamente os do [protocolo de cauda](macro_tail_risk_protocol_2026-09-27.md).
- A decisão ocorre domingo às 23:00 UTC para entrada na abertura de segunda às 00:00 UTC. Como a API não documenta um horário intradiário confiável de publicação, usar como corte do FGI o último timestamp igual ou anterior à decisão menos 48 horas.
- Criar três variáveis numéricas: nível FGI dividido por 100; diferença do nível atual para a última observação disponível até 7 dias antes do timestamp corrente; e a mesma diferença para 30 dias. Cada referência histórica usa o registro mais recente no corte ou antes dele; não interpolar nem preencher dados futuros.
- Conservar, por decisão, o timestamp da observação corrente, sua idade em horas e os valores brutos usados, para auditoria.

## Comparações congeladas

Treinar expansivamente um `StandardScaler` seguido de `QuantileRegressor(quantile=0.10, alpha=0.01, solver="highs")`, separadamente por ativo, com pelo menos 52 alvos semanais completos. Nenhuma busca de hiperparâmetros será executada. Os quatro modelos são:

1. `price_only`: retornos próprios de 1, 4 e 12 semanas.
2. `price_plus_macro`: controle macro já testado, com as mesmas três séries externas e lags do estudo anterior.
3. `price_plus_fgi`: `price_only` mais as três features FGI.
4. `price_plus_macro_fgi`: `price_plus_macro` mais as três features FGI; candidato primário.

Para cada métrica preditiva, comparar os quatro modelos nas mesmas combinações de semana/ativo disponíveis a todos. Reportar perda pinball q10, cobertura, quantil de treino e referências zero/treino. A melhora de pinball é necessária, mas não equivale a lucro.

## Replay e critério

Aplicar a cada previsão a regra anterior, sem alteração: por ativo, exposição `min(100%, 4% / max(1%, -q10))` do saldo da conta; rebalanceamento semanal na abertura de segunda; Spot long/cash; quatro parcelas iniciais iguais; custos de 0,15% e 0,30% por lado. Comparar com preço apenas, macro sem FGI, comprar e manter e caixa. Reutilizar as janelas walk-forward comum e holdout iniciado em 06/01/2025, encerrado em 31/08/2026.

Para considerar evidência histórica compatível com a meta local, o candidato primário precisa melhorar a perda pinball contra `price_plus_macro` tanto no walk-forward comum quanto no holdout final e alcançar CAGR líquido de pelo menos 50% com drawdown adverso intrahorário de no máximo 10% nas duas janelas e nos dois custos. Mesmo se passar, dados retrospectivos não autorizam operação: o ganho precisa ser confirmado em paper prospectivo, com parâmetros e regras congelados.

Nenhuma chamada JEV, ordem real ou alteração do watcher paper será feita. Não adicionar parâmetros após observar os resultados.
