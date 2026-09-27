# Previsão horária absoluta do BTC com retenção por custo

Hipótese: uma previsão do retorno absoluto horário do BTC pode ser mais útil ao controlar transições entre comprado e caixa do que ao converter cada oscilação de sinal em uma ordem. O teste combina um alvo e relógio ainda não avaliados localmente com uma comparação explícita da regra de transição. A [nota de fontes](hourly_forecast_sources_2026-09-26.md) distingue esta hipótese das pesquisas locais e aponta problemas no artigo motivador. Este estudo não replica seus resultados, seus dados, sua biblioteca ou seu processo de seleção.

A meta continua sendo CAGR líquido de 50% sobre o capital total e drawdown máximo de 10%. Não reduzir a meta, aumentar risco depois do resultado nem chamar lucro isolado de consistência. O histórico já foi consultado em outras pesquisas; os períodos são comparações cronológicas retrospectivas, sem alegação de confirmação intocada. Nenhuma alteração no candidato ou no processo paper existente.

## Mercado e informação

BTCUSDT spot, somente comprado ou caixa, sem empréstimo ou alavancagem. Verificar os mesmos 712 ZIPs e três manifestos fixados pelo inventário de basis; utilizar BTC para os indicadores e os preços spot para a carteira. Funding e perp são contexto preditivo, sem transferências de funding na conta spot. Caixa rende zero. Não substituir ausência de informação por dados futuros nem remover lacunas do inventário.

Reutilizar a construção causal de `basis_features` somente para BTC. A cada execução `t`, o último candle considerado abriu em `t-2h` e terminou em `t-1h`; uma hora completa fica entre fechamento e execução. Funding considerado tem timestamp até `t-2h`, com hipótese explícita de publicação uma hora após o evento. O arquivo atual não comprova a disponibilidade histórica. Reiniciar indicadores após lacunas. As primeiras 720 horas e o novo aquecimento após o buraco de março de 2023 não geram estado elegível.

Usar todas as folhas técnicas dos pacotes spot e perp: médias, inclinação, ADX/DI, momentum, RSI, MACD, estocástico, ATR, volatilidade, Bollinger, drawdown, participação, volumes, VWAP, estrutura e Fibonacci. As janelas são barras horárias. Acrescentar basis negociado/mark, mediana e desvio dos 720 valores anteriores, funding médio/mínimo/recente e número de eventos em 30 dias, volumes das últimas 24 horas, seno/cosseno da hora UTC e do dia da semana no fechamento observado. Preservar `None` nos dados. Preços nominais, timestamps, hashes e identificação de ativo não entram no vetor numérico. O esquema e o hash completo dos estados serão congelados antes de calcular previsões ou resultados.

## Alvo e aprendizagem

Prever `open_spot[t+1h]/open_spot[t]-1`. O alvo é retorno bruto da hora seguinte à execução, sem centrar entre ativos, aplicar hedge ou somar funding. Os candles de entrada e saída devem existir e ter volume positivo e número inteiro positivo de negócios para validar um rótulo depois do fato. Volume cotado, quando presente, também deve ser finito e positivo; sua ausência não é preenchida. A mesma validação de liquidez se aplica aos fills. A qualidade do candle da saída só é conhecida após ele terminar: disponibilidade do rótulo em `t+2h`, exigindo esse horário estritamente anterior ao corte de informação da previsão corrente. Rótulo futuro ausente ou sem liquidez impede pontuar/treinar aquela observação; não impede emitir a previsão corrente.

Janela móvel de 365 dias pela data de execução do rótulo em relação ao corte atual. Exigir pelo menos 4.320 rótulos completos. Ajustar no primeiro corte elegível de cada mês UTC, conservando o ajuste até o mês seguinte. Assim o início efetivo pode ocorrer muito depois do começo do período de desenvolvimento; não encurtar a janela de avaliação para esconder esse caixa inicial. As amostras, rótulos, agenda e pesos unitários são os mesmos para os dois previsores:

- Média simples dos retornos de treino, como controle sem condicionamento nos indicadores.
- HistGradientBoostingRegressor, loss `squared_error`, learning_rate 0,05, max_iter 100, max_leaf_nodes 7, max_depth 3, min_samples_leaf 40, l2_regularization 10, max_bins 64, categorical_features None, early_stopping False, random_state 548 e um thread numérico. Reutilizar esses parâmetros fixos da pesquisa anterior, sem procurar outros pelo desempenho.

Converter `None` em NaN apenas na matriz. Se uma coluna inteira estiver ausente no treino de um ajuste, usar zero na matriz de treino e previsão daquela coluna até o próximo ajuste; a máscara depende somente do treino e os estados brutos permanecem ausentes. Guardar hashes das matrizes bruta/efetiva, rótulos, amostras, pesos, máscara, ajustes e previsões. Exigir causalidade por testes de alteração de dados futuros. Não tratar a previsão como probabilidade calibrada de lucro.

## Decisão, custos e proteção

Aplicar duas regras ao mesmo previsor:

- `sign`: entrar quando a previsão for positiva, sair quando for zero ou negativa.
- `cost_band`: entrar quando a previsão exceder duas vezes o custo por lado; sair quando for estritamente menor que o negativo desse limiar. Dentro da faixa, inclusive nas bordas, manter o estado e a quantidade existentes. Uma previsão positiva pequena não força entrada; uma negativa pequena não força saída.

Custos por execução: 0,12% no cenário base e 0,24% no stress. Base presume 0,10% de taxa spot e 0,02% de deslizamento; não prova a tarifa individual ou histórica. Cobrar sobre o notional de cada compra/venda. Na regra de banda, dobrar o custo também altera o limiar e pode mudar o caminho das operações. Na regra sign, o custo afeta caixa, quantidade e eventuais stops, sem mudar o sinal bruto. A banda usa uma aproximação de custo de ida e volta, não uma equação de lucro garantido durante toda a permanência.

Na entrada alocar 50% ou 100% do patrimônio: `q = fração*patrimônio/[open*(1+custo)]`. Manter q até a saída, sem rebalancear por hora. Logo, 50% é alocação na entrada e não um teto de exposição constante após variações do preço. Caixa e inventário precisam reconciliar; nenhuma taxa pode gerar dinheiro ou ser contada duas vezes. Preenchimentos horários e custos são aproximações; volume/negócios positivos são verificados posteriormente, não antecipados como sinal. Falta de preço durante posição aberta ou liquidez inválida em fill invalida o cenário.

Comparar sem trailing e com trailing de carteira de 4%, avaliado nas aberturas. O stop fecha antes da política e proíbe reentrada na mesma hora; pode haver nova entrada na hora seguinte. Seu pico reinicia quando a conta fica em caixa, mas o pico global do drawdown não reinicia. Incluir capital e taxas de entrada no risco. O fechamento terminal inclui custos e impede nova compra. O trailing não garante perda máxima por operação ou por carteira.

Calcular drawdown observado antes/depois das ordens e limite adverso intrahora incorporando picos favoráveis possíveis e vales adversos. Para long spot, patrimônio favorável é `caixa+q*high` e adverso `caixa+q*low`; a ordem intrahora não é conhecida, então o limite é conservador. Incluir taxas terminais no confronto com os picos anteriores. A [clarificação do cálculo antigo](intrahour_bound_clarification_2026-09-26.md) preserva a distinção entre esse limite e o campo dos executores antigos; não alterar seus resultados congelados.

## Comparações fixadas

São 64 cenários preditivos: dois previsores, duas regras, dois custos, duas alocações, dois trailings e dois períodos. Mais oito referências `buy_hold`, combinando custos, alocações e períodos, sem trailing. Essa referência compra na primeira previsão elegível do período, independentemente do valor previsto, e mantém até o término; antes disso fica em caixa como os previsores. Não escolher um vencedor com base no resultado posterior.

Desenvolvimento de 01/01/2023 a 01/01/2024; período posterior de 01/01/2024 a 31/08/2026 às 23h UTC, todos com capital inicial unitário. Treino pode usar o passado disponível antes do início de cada período. Não simular abertura de setembro ausente do cache. CAGR usa todo o tempo decorrido em anos de 365,25 dias, incluindo aquecimento e caixa. Reportar retorno, CAGR, drawdown observado/limite, custos, PnL de preço, entradas, giro, exposição, stops, meses, anos, curvas e reconciliação. Mensurar também erro de previsão e comparação pareada com a média, usando somente rótulos completos após o fato. Acurácia ou erro quadrático isolados não demonstram lucro econômico.

Congelar protocolo, código, testes, ambiente e inputs antes das previsões reais. Preservar todos os cenários, inclusive inválidos. Não chamar JEV neste estudo: seu contrato continua uma chamada agrupada por ativo/instante para pontuar aderência; a decisão pertence ao script. Nenhuma ordem, download de mercado ou novo gasto de API é necessário.

```json
{
  "schema_version": 1,
  "symbol": "BTCUSDT",
  "periods": {
    "development": ["2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
    "later": ["2024-01-01T00:00:00+00:00", "2026-08-31T23:00:00+00:00"]
  },
  "models": ["rolling_mean", "hgb"],
  "modes": ["sign", "cost_band"],
  "side_costs": [0.0012, 0.0024],
  "allocations": [0.5, 1.0],
  "portfolio_trailing": [null, 0.04],
  "label_hours": 1,
  "label_quality_delay_hours": 1,
  "execution_delay_hours": 1,
  "rolling_training_days": 365,
  "minimum_training_rows": 4320,
  "refit": "first_eligible_monthly_cutoff",
  "cost_band_multiple": 2,
  "target_net_cagr_pct": 50,
  "maximum_drawdown_pct": 10,
  "historical_point_in_time_verified": false
}
```
