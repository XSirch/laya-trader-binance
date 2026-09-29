# Diário do estudo de fluxo defasado

## Tentativa 1: simulação interrompida

O replay montou o painel e concluiu os ajustes walk-forward mensais dos modelos, mas parou ao simular o primeiro cenário `rolling_mean`. O executor manteve em `current_bars` o candle de uma posição que acabara de fechar e depois tentou usar essa barra como posição ativa. O resultado foi `KeyError: 'SOLUSDT'` em `lagged_flow_execution.py`, durante a marcação horária da carteira. Nenhuma métrica dessa tentativa foi aceita como resultado.

O snapshot dos insumos que ancorou essa tentativa foi preservado em `results/lagged_flow_inputs_attempt2_failed_run.json` e `results/lagged_flow_inputs_attempt3_pre_fix.json`. O erro não implicou dados ausentes de SOL nem sinal de trading; foi um defeito do replay. A correção remove do mapa de barras a posição no mesmo momento em que o executor encerra essa posição. A nova execução precisa congelar novamente os insumos, pois o hash do executor mudou.

## Tentativa 2: métricas calculadas, relatório não serializado

Com o executor corrigido, os 20 cenários chegaram ao fim, mas a gravação do relatório parou porque as previsões e rótulos usavam chaves Python compostas por `(horário, ativo)`, que JSON não aceita como chave de objeto. Não houve relatório final gravado; os números no terminal são apenas diagnóstico e precisam ser reproduzidos pela nova execução. Nesse diagnóstico, CAGR posterior do HGB com dados próprios foi -29,30% a 0,15% por lado e -15,98% a 0,30%; com lags de BTC/ETH foi -10,14% e -13,85%, respectivamente. A redução da perda aparente é uma pista para comparar incrementalmente os lags, mas não transforma os modelos em estratégias lucrativas. Buy-and-hold marcou -14,28% posterior a 0,15%.

O snapshot dessa tentativa está preservado em `results/lagged_flow_inputs_attempt4_failed_report.json`. O serializador agora representa previsões e rótulos como listas de registros com `execution_ms` e `symbol`, preservando cada observação sem chaves compostas. A nova execução precisa reancorar e reproduzir todas as métricas antes de qualquer conclusão.

## Tentativa corrigida e concluída

O serializador preserva previsões e rótulos como listas de registros com `execution_ms` e `symbol`. Os 20 cenários e seus hashes foram gravados em `docs/lagged_flow_research_2026-09-27.json` e `results/lagged_flow_research.json`; resumo e relatório integral concordam no SHA-256 `d41ed243b720185314aaffa819fb72dfd353cf886be5c672430a6f25acf0a9c1`. O novo snapshot de entrada tem SHA-256 `293ed8567f5901b83a74f3f447c6a46825d8c41d55a5d267a8257918a46ed1f3`.

O replay levou 443 segundos e concluiu 32 ajustes mensais, 15.348 eventos e 20 cenários. Reproduziu exatamente as métricas diagnósticas descritas na tentativa 2. Nenhum cenário atingiu a meta; o posterior do HGB com lags de BTC/ETH foi -10,14% de CAGR e 36,49% de limite adverso a 0,15% por lado, e -13,85% e 37,40% ao custo estressado. Em 2025 o primeiro cenário teve retorno anual de +9,10%, seguido por -23,29% no trecho janeiro–agosto/2026. `goal_achieved=false` e `deployable=false`.

O experimento usou o cache existente: zero downloads, gravações de cache, chamadas JEV e ordens. Veja [resultado e limites](lagged_flow_research_2026-09-27.md). As etapas anteriores continuam preservadas; nenhuma métrica de uma tentativa sem relatório foi promovida a resultado final.

## Ablação dos lags

Para isolar a pequena melhora observada com o painel amplo, congelei e rodei a comparação entre lags próprios, somente BTC/ETH e a combinação, usando os mesmos rótulos, folds e custos. O protocolo e resultado estão em `lagged_flow_ablation_protocol_2026-09-27.md` e `lagged_flow_ablation_research_2026-09-27.md`. A grade completa permaneceu negativa; o melhor foi -5,74% de CAGR posterior, com 19,77% de drawdown adverso. O grupo vencedor muda entre 2025 e 2026, sem skill contra retorno zero. Essa família também foi rejeitada e nenhuma operação foi autorizada.


## Holdout temporal de setembro concluído

O replay congelado executou 33 ajustes walk-forward e completou os 10 cenários em 216 segundos. Os dados Spot diários de setembro foram validados por checksum: 104 arquivos, 2.496 candles, 208 requisições de arquivo/ checksum. Foram pontuadas 308 previsões por modelo. Os seis cenários ML retornaram +0,35% e -0,29% (lags próprios), -3,53% e -2,57% (lags de BTC/ETH), -2,69% e -1,71% (combinação), nos custos de 0,15% e 0,30% por lado. Os controles buy-and-hold retornaram +11,29% e +10,96%; sempre comprado, -11,34% e -29,63%. Nenhum caso ML atingiu o gate; o resultado curto não prova consistência anual. `historical_point_in_time_verified=false` permanece como limite explícito. Resumo e hashes em `lagged_flow_forward_research_2026-09-27.md` e `.json`; relatório integral SHA-256 `29e4a4772d94812da004973d975dc2a45e51216aec463427b2465896e2be7bae`; entradas SHA-256 `08154099d68d2929d42e167f66276699faec3b3bbcd6548275fe0b27e5dc59cb`. Nenhuma ordem foi enviada, `goal_achieved=false` e `deployable=false`.

## Hipótese nova: GainzAlgo V2 Alpha

A página do fornecedor foi consultada em 27/09/2026 e descreve o Alpha como preset do indicador privado TradingView, com sinais BUY/SELL e níveis TP/SL, recomendado pelo próprio vendedor para 1m–1h. A lógica e uma série íntegra de sinais não são publicadas em formato reproduzível. A avaliação e o protocolo de dados mínimos estão em `gainzalgo_v2_alpha_assessment_2026-09-27.md`. Nenhum sinal do produto foi simulado; isso não é aprovação nem rejeição da estratégia.
