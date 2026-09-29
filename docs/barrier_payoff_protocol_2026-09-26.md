# Protocolo de previsão do resultado da operação

A meta permanece CAGR líquido de 50% sobre o capital total e drawdown máximo de 10%. A hipótese nova é alinhar o retorno previsto à política completa de saída: lucro, stop ou prazo. Não repetir a previsão de uma hora com retenção indefinida. O inventário não encontrou esse alvo nos estudos anteriores. As [fontes](barrier_payoff_sources_2026-09-26.md) distinguem a definição de barreiras desta adaptação local; não demonstram rentabilidade da nossa regra.

O levantamento de [propagação entre ativos](cross_asset_sources_2026-09-26.md) encontrou efeitos econômicos em outros relógios, sem validar nossa espera adicional de uma hora. Esse replay não será iniciado nesta rodada. A falta dessa validação não prova ausência de efeito; evita apresentar outra hipótese exploratória como reprodução de vantagem estabelecida.

## Dados e indicadores

Reutilizar exatamente os 114 campos de `hourly_forecast_features` para BTCUSDT, derivados dos candles spot/perp, mark e funding verificados por `basis_data`. O conjunto tem médias, Fibonacci, momentum, volatilidade, volume, participação, estrutura e variáveis econômicas. Os 712 ZIPs e três manifestos do inventário permanecem fixados. Não baixar mercado, não chamar JEV e não enviar ordens.

Na execução `t`, o candle mais recente considerado abriu em `t-2h` e fechou em `t-1h`. Funding segue o atraso presumido já documentado; disponibilidade histórica não é comprovada. Ausências e reinício após lacunas permanecem preservados. Nenhuma data, identificação, preço nominal ou rótulo futuro entra na matriz numérica.

## Episódio e rótulo

Usar a fração `a = spot.volatility.atr14_pct / 100`, conhecida no corte de informação. Exigir `0 < a < 1`; ausência impede entrada/previsão e valor inválido presente é erro. Fixar as distâncias a partir do preço de entrada: stop `open[t]*(1-a)` e alvo `open[t]*(1+2*a)`. Isso escala o ATR percentual à abertura executada; não mantém o ATR absoluto do candle antigo. Não recalcular distâncias durante a posição.

O prazo é a abertura exata `t+8h`. Cada barra valida OHLC consistente, volume base e número inteiro de negócios positivos; volume cotado, quando fornecido, também deve ser positivo e finito. A validação é posterior ao fato, nunca critério futuro de entrada.

Prioridade de saída: gap de abertura abaixo/do stop, no preço de abertura; gap de abertura acima/do alvo, no preço do alvo; prazo na abertura; stop intrabar; alvo intrabar. Quando stop e alvo são tocados na mesma barra, assumir stop primeiro. O preenchimento favorável é limitado ao alvo mesmo quando o gap ultrapassa esse preço. São hipóteses de execução com candles, sem livro ou ordem real comprovada. Não atribuir horário exato a preenchimento intrabar: registrar a barra e a fase.

Rótulo bruto é `preço_saída/preço_entrada - 1`, antes de taxas. Disponibilidade é o fechamento do candle da saída, inclusive quando a saída ocorre na abertura, pois só então a qualidade completa desse candle é conhecida. O timeout pode tornar o rótulo disponível em `t+9h`; um stop cedo pode disponibilizá-lo antes. Portanto, a disponibilidade não é monotônica pela data da entrada. O treino deve processar eventos por disponibilidade e admitir somente `available_ms < cutoff`. Uma observação antiga ainda aberta não impede que uma mais nova já encerrada seja elegível.

Gerar um episódio potencial para cada estado elegível. Esses episódios de treino podem se sobrepor e não são amostras independentes. A simulação financeira não sobrepõe posições. Ausência ou qualidade inválida durante um episódio impede usar seu rótulo; não impede emitir a previsão corrente com informação passada suficiente. O executor verifica a condição real quando chega à barra e invalida o cenário se houver falta de preço/qualidade durante posição ou fill.

## Aprendizagem e decisão

Usar média histórica dos payoffs e HGB com os parâmetros fixos da pesquisa horária, sem busca de hiperparâmetros. Mesmos estados, rótulos, pesos unitários e agenda para ambos. Janela de 365 dias pela entrada do evento em relação ao corte, incluindo a borda inferior; mínimo de 4.320 episódios completos. Ajuste no primeiro corte elegível de cada mês UTC. Se a quantidade elegível cair abaixo do mínimo, não emitir previsão mesmo havendo modelo anterior.

Preservar `None` no dado bruto. Converter para NaN apenas na matriz; colunas inteiramente ausentes no treino são zero até o próximo ajuste. Máscara e qualquer transformação dependem somente do treino. Registrar identidades, datas, matrizes, rótulos, máscaras, modelos e previsões por hash. Reutilizar loss squared_error, learning_rate 0,05, max_iter 100, max_leaf_nodes 7, max_depth 3, min_samples_leaf 40, l2_regularization 10, max_bins 64, categorical_features None, early_stopping False, random_state 548 e um thread numérico.

Para custo proporcional por lado `c`, o ganho líquido por unidade de capital aplicada é `(1+r)*(1-c)/(1+c)-1`. Portanto, o limiar bruto exato de equilíbrio é `2*c/(1-c)`. O script entra somente quando `min(previsão_bruta, 2*a)` for estritamente maior que esse limiar. O teto vem do payoff máximo permitido pelo alvo conservador, calculado com informação corrente. Manter previsão original, valor efetivo, teto e limiar no registro da decisão. A regra é a mesma para a média e o HGB. A previsão não é probabilidade de lucro nem garantia de preenchimento.

Comprar apenas estando em caixa. Na entrada, `q = alocação*patrimônio/[open*(1+c)]`; manter q até a saída. Comparar alocações de 50% e 100%, sem alavancagem, empréstimos, funding financeiro ou juros sobre caixa. A fração vale na entrada, não é limite constante após os preços mudarem. Cobrar cada compra/venda sobre seu valor negociado. Custo base 0,12% por lado e stress 0,24%; são hipóteses, não comprovação da tarifa particular. Alterar custo pode alterar entradas e caminho da carteira.

Não reentrar na mesma barra de uma saída. Para a política com barreiras, não abrir se `t+8h > fim_do_período`; esse prazo de pesquisa é conhecido antes da entrada. Forçar fechamento terminal com custo se necessário. Não ajustar saídas com base em novas previsões. Não adicionar trailing nesta hipótese; sua avaliação anterior permanece registrada, e o stop deste estudo é fixo por episódio.

Controles: `always` entra sempre que está em caixa e há previsão/estado válido, ignorando o escore, e usa as mesmas barreiras; `buy_hold` compra na primeira previsão/estado válido e mantém até o final, ignorando barreiras e limite de oito horas. Ambos seguem o calendário de previsões da média. Não antecipar entrada dos controles ao aquecimento dos modelos.

## Avaliação e congelamento

Grade de 32 cenários: média/HGB/always, dois custos, duas alocações e dois períodos (24), mais buy_hold nas mesmas combinações de custo/alocação/período (8). Desenvolvimento de 01/01/2023 a 01/01/2024; posterior de 01/01/2024 a 31/08/2026 às 23h UTC. Cada período começa com capital unitário. CAGR usa todo o calendário de 365,25 dias por ano, inclusive aquecimento e caixa.

Guardar fills, caixa, quantidades, PnL, taxas, decisões, motivos, digest de permanências, exposição, curvas, meses e anos. Mensurar drawdown em aberturas, fechamentos e após fills. A série horária regular usa patrimônio após ações na abertura; marcas intrabar ficam separadas, sem precisão temporal fictícia. Dias e meses seguem essa convenção de abertura, incluindo a taxa terminal. O limite adverso conservador usa high/low de toda barra com exposição intrabar, mesmo quando a saída hipotética ocorre dentro dela; exclui extremos posteriores somente para saída na abertura. Ele pode ser mais pessimista que o caminho financeiro adotado e não comprova execução de stop.

Comparar MSE/MAE dos payoffs brutos em episódios cuja disponibilidade inteira caiba no período. Essas métricas e acerto de sinal não provam resultado econômico; episódios sobrepostos não formam replicações independentes. Relatar todos os cenários e invalidar falhas de execução esperadas sem esconder erros de implementação.

Congelar protocolo, código, testes, fontes, runtime e inputs antes de qualquer previsão ou replay real. O histórico já foi examinado; comparação cronológica não é holdout intocado. Não escolher vencedor pelo período posterior, não promover resultado isolado para operação real e não modificar o candidato/coleta paper existentes. O contrato do JEV permanece uma chamada agrupada para pontuar aderência; a decisão é do script.

```json
{
  "schema_version": 1,
  "symbol": "BTCUSDT",
  "periods": {
    "development": ["2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
    "later": ["2024-01-01T00:00:00+00:00", "2026-08-31T23:00:00+00:00"]
  },
  "models": ["rolling_mean", "hgb", "always", "buy_hold"],
  "side_costs": [0.0012, 0.0024],
  "allocations": [0.5, 1.0],
  "stop_atr": 1,
  "target_atr": 2,
  "max_hours": 8,
  "execution_delay_hours": 1,
  "rolling_training_days": 365,
  "minimum_training_rows": 4320,
  "refit": "first_eligible_monthly_cutoff",
  "target_net_cagr_pct": 50,
  "maximum_drawdown_pct": 10,
  "historical_point_in_time_verified": false
}
```
