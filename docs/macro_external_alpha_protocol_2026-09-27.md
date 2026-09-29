# Protocolo: sinais semanais com variáveis externas de mercado

## Hipótese e relação com o histórico

Os experimentos anteriores já testaram tendência, momentum, fluxo e dezenas de campos próprios de cripto, incluindo modelos de ML. A avaliação independente inspirada apenas nas categorias públicas do GainzAlgo V2 Alpha também foi negativa; o fornecedor não divulga a fórmula do Alpha. As séries de ações, VIX e dólar não aparecem nos protocolos anteriores. Esta rodada pergunta se informação externa defasada melhora uma previsão semanal cripto que já recebe lags do próprio ativo.

A literatura é mista: um estudo recente de Bitcoin encontrou resultados econômicos condicionais para alguns preditores, mas vantagem estatística de previsão não se converteu uniformemente em lucro; VIX não foi estável. O teste não presume que as conclusões sobre USD Index ou bolsa se transfiram ao índice amplo do Fed, aos quatro pares Binance ou a esta amostra. Fontes e limitações estão em [macro_crypto_sources_2026-09-27.md](macro_crypto_sources_2026-09-27.md).

Todo o histórico de preço cripto deste replay já apareceu em estudos anteriores. O protocolo e as variáveis externas são novos, mas qualquer avaliação histórica é exploratória, não um holdout intocado do projeto. Nenhum resultado retrospectivo autoriza negociação real.

## Dados, relógio e variáveis congeladas

- Universo: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT spot; quatro saldos isolados com 25% do capital inicial cada, sem alavancagem, shorts ou transferência entre saldos.
- Período: primeira segunda-feira às 00:00 UTC que segue todas as lacunas arquivadas até a última segunda-feira às 00:00 UTC com uma semana completa no histórico horário. O inventário atual aponta de 27/03/2023 a 24/08/2026 para entradas, com liquidação final em 31/08/2026.
- Decisão: domingo às 23:00 UTC, antes da abertura da semana. Entrada e saída, quando necessárias, na abertura do candle Binance de segunda-feira às 00:00 UTC. Uma observação semanal tem como alvo o retorno simples entre aberturas consecutivas de segunda-feira.
- Dados externos: Nasdaq Composite (`NASDAQCOM`), VIX (`VIXCLS`) e índice nominal amplo do dólar do Fed (`DTWEXBGS`), todos baixados individualmente do gráfico ALFRED com `vintage_date` igual ao domingo de decisão e janela dos 90 dias anteriores. A função registra para cada snapshot o SHA-256, a data da observação mais recente disponível e a idade em dias. Além das 21 observações necessárias para uma variação de 20 sessões, Nasdaq e VIX precisam ter observação mais recente com até 7 dias; o dólar precisa ter até 14 dias, respeitando a liberação semanal H.10. Esses limites não carregam revisões ou valores futuros: semanas sem frescor/histórico suficiente não produzem característica macro nem entram no treino desse modelo.
- Características macro, em retornos logarítmicos: variação em 1, 5 e 20 observações disponíveis para cada uma das três séries. As janelas são observações da própria série, não dias corridos; feriados e fins de semana carregam a última observação realmente presente na vintage.
- Controle cripto: retornos simples do próprio ativo nas últimas 1, 4 e 12 semanas, medidos entre aberturas semanais anteriores à decisão.
- Comparação preditiva fixada: dois modelos Ridge com intercepto e padronização fitada somente em cada janela de treino: `price_only` (três controles cripto) e `price_plus_macro` (os mesmos controles mais nove campos macro), alpha 1,0. Reajuste expansivo por ativo e semana. Exigir pelo menos 52 retornos semanais integralmente finalizados antes do corte; o rótulo que termina na própria entrada não pode treinar o modelo daquele corte.

Se a observação mais recente de qualquer série não tiver 20 valores válidos, exceder o limite de idade acima, ou uma característica não puder ser calculada, não emitir sinal naquela semana para o modelo macro. O modelo de controle preço-only continua sendo calculado. Não interpolar dados, não preencher com observações futuras, não ajustar hiperparâmetros e não buscar outras séries, janelas ou indicadores após observar os resultados.

## Regra de carteira e execução simulada

Para cada modelo, ativo e custo, manter a conta em caixa ou 100% comprada no respectivo ativo. A cada segunda-feira, ficar comprado se e somente se o retorno semanal previsto exceder estritamente o limite de equilíbrio `2*c/(1-c)`, onde `c` é o custo por lado. Permanecer comprado sem ordem quando a decisão seguinte continuar comprada; vender na abertura semanal quando mudar para caixa. Liquidar no limite final. Registrar uma variante para `c=0,15%` e outra para `c=0,30%` por lado, como nas avaliações anteriores de estratégias spot.

Entradas executam a preço de abertura mais a taxa no nocional; vendas executam na abertura menos a taxa no nocional, como nos outros replays do repositório. OHLC horário sustenta a marcação de patrimônio e um limite adverso pelas mínimas durante a exposição, mas não prova fill, spread, slippage nem ordem intrabar. Não modelar impostos, juros sobre caixa ou rendimento de stablecoin. Comparadores: dinheiro parado; buy-and-hold comprado uma vez no primeiro instante de avaliação e liquidado no último, com o mesmo peso inicial e custos. O modelo `price_only` é também o comparador principal para a contribuição das variáveis externas.

## Cortes, métricas e decisão

Gerar previsões em walk-forward com todos os cortes para os quais existam 52 semanas de treino. Reportar separadamente (a) o intervalo walk-forward completo, (b) desenvolvimento de 2024 e (c) holdout temporal fixado de 06/01/2025 até a liquidação em 31/08/2026. O holdout final é uma avaliação cronológica deste protocolo específico; o período de preço já foi visto em outras pesquisas do projeto.

Para previsões, reportar número de datas, MSE e MAE contra retorno zero, média expansiva e entre os dois Ridge; precisão direcional é apenas descritiva. Para carteiras, reportar retorno líquido, CAGR, drawdown observado nas aberturas, limite adverso por mínimas horárias, taxa de acerto de semanas expostas, semanas/meses/anos positivos, tempo investido, giros, ordens, taxas e resultados por ativo/custo/período. A comparação macro deve incluir a diferença pareada de erro e retorno entre `price_plus_macro` e `price_only`, sem escolher o ativo vencedor.

A meta do usuário continua sendo pelo menos 50% de CAGR líquido e drawdown total máximo de 10%; os dois requisitos precisam ser satisfeitos, sem ignorar o limite adverso. Além disso, um achado lucrativo neste replay ainda não passa o gate prospectivo: precisa de meses futuros congelados em paper, resultado líquido favorável com custo realista e consistência entre ativos/períodos. Não chamar previsão direcional ou taxa de acerto de lucro consistente. Se nenhum resultado passar, rejeitar a hipótese, registrar a conclusão e seguir para uma nova família não testada, sem retunar este mesmo período.

## Reprodução e direitos dos dados

Guardar respostas brutas ALFRED apenas no cache local ignorado em `.cache/macro_external_alpha/`. Não copiar valores de séries para relatórios versionáveis ou redistribuí-los; registrar hashes dos arquivos, identificadores, datas de vintage e versões de código. Antes de divulgar curvas, produtos ou resultados derivados de NASDAQCOM e VIXCLS, confirmar a licença aplicável a Nasdaq e Cboe. O acesso às páginas FRED não concede automaticamente direito de republicação.

Não enviar ordens, não chamar JEV e não alterar a carteira de acompanhamento. O protocolo, os códigos, os hashes e resultados deverão ser registrados antes de qualquer conclusão.
