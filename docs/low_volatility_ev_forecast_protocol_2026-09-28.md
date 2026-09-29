# Protocolo: prever EV por operação em futuros de baixa volatilidade

## Hipótese e relação com estudos anteriores

O candidato-base `low_volatility30_betahedged` foi escolhido porque, entre os replays já feitos, combinou EV e payoff altos com drawdown abaixo de 10% no filtro HGB, embora tenha ficado em 62,9% de acerto no combinado. O filtro anterior previa apenas vitória/derrota. Esta hipótese usa regressão para prever o retorno líquido da operação completa; não retreina os cortes de entrada do candidato-base.

O estudo é exploratório e retrospectivo: as janelas foram vistas no scorecard anterior. Mesmo um resultado favorável só gera um candidato para paper prospectivo. Mercado negociado: somente perpétuos Binance USD-M; sem ETF, ações, alavancagem ou ordem real.

## Dados, rótulos e corte temporal

Reutilizar o ledger congelado `results/broad_trade_ledger_20260927.csv`, as features causais já calculadas em `broad_research.py` e as mesmas janelas e custo por lado do filtro anterior. Excluir rótulos combinados, saídas proxy, posições terminais sem preço observado, retornos nulos e qualquer linha sem estado no instante de entrada. O rótulo é o retorno líquido completo sobre o notional inicial da operação a custo de estresse de 0,15% por lado.

Em cada segunda-feira UTC, treinar apenas com operações cuja saída ocorreu estritamente antes da decisão e cuja entrada esteja nos 104 dias-semana anteriores. Exigir no mínimo 100 operações completas. Vetor fixo: `momentum7`, `momentum30`, `momentum90`, `reversal1`, `reversal7`, `carry30`, `volatility`, `taker_flow20`, `beta60`, `time_series_ensemble` e direção da posição. Não incluir símbolo, data ou retorno futuro.

## Modelo, decisão e métricas

Modelo fixo: `HistGradientBoostingRegressor(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=15, l2_regularization=2.0, early_stopping=False, random_state=2026)`. Sem otimização de features, hiperparâmetros ou limiar. Abrir/continuar apenas pernas com retorno líquido previsto `>=1.2%` do notional de cada episódio. Reequilibrar as pernas aceitas com 25% de notional bruto por lado, igual ao teste anterior; exigir ao menos uma perna longa e uma curta para manter neutralidade beta.

Executar o mesmo replay de episódios, custos, funding, marcação adversa e saídas do motor anterior. Gates sob custo de estresse em `validation_2025h2` e `confirmation_2026`: acerto `>=70%`, payoff `>=1:1`, EV observado `>1.2%` por episódio no notional, drawdown `<=10%`, ao menos 30 episódios resolvidos. O combinado também precisa de drawdown `<=10%`. Relatar cenário-base separadamente. Não tratar as janelas retrospectivas como confirmação prospectiva.

## Proveniência e limites

O estudo só reutiliza dados e ledger existentes; não consulta ou envia ordens ao JEV, não acessa conta e não altera o observador paper de um minuto. Probabilidades/retornos previstos por HGB não são probabilidades calibradas. Episódios entre ativos podem ocorrer na mesma semana e os rótulos compartilham condições de mercado.

