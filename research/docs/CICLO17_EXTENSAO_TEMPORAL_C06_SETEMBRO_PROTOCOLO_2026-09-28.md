# Ciclo 17 — extensão temporal congelada do C06 em setembro

Data: 28/09/2026  
Status: pré-registro; não baixar os arquivos nem gerar scores antes de registrar os hashes do protocolo e do runner no ledger.

## Pergunta

O seletor mensal de expectativa direta do C06, sem mudar scanner, features, política de saída, risco ou corte, mantém algum sinal econômico em BTCUSDT e ETHUSDT USD-M durante setembro de 2026?

## Novidade e limite de independência

O C16 terminou a janela em 01/09/2026 e determinou que a linha C06 aguarde avaliação temporal futura, sem recalibração sobre a janela já vista. Este ciclo desloca a avaliação para setembro e acrescenta um único refit mensal, usando apenas rótulos que já estavam maduros às 00:00 UTC de 01/09. Não retreinar com dados de setembro.

Esta janela não é um holdout global intocado. No USD-M, o Ciclo 11 avaliou `rank_blend` até 26/09/2026. Estudos separados também avaliaram BTC/ETH e outros pares Spot durante setembro, e um paper BTCUSDT Spot estava em andamento. A regra e o score C06 não foram avaliados por esses trabalhos, mas parte do mesmo período e dos mesmos ativos cripto já foi observada em outras análises. Classificar C17 como extensão temporal retrospectiva exploratória; não chamar o resultado de validação independente, confirmação prospectiva ou estratégia aprovada.

Registros de sobreposição consultados: `research/docs/CICLO11_RANK_BLEND_EXTENSION_PROTOCOLO.md`, `docs/lagged_flow_forward_protocol_2026-09-27.md`, `docs/crypto_liquidity_alpha_research_2026-09-27.md` e `docs/minute_jev_paper_interim_2026-09-28.md`.

O teste cobre somente 27 dias de sinais e não pode satisfazer a exigência de pelo menos oito semanas ativas. Serve como evidência adicional ou falsificação da transferência temporal congelada; não pode, por si só, aprovar a estratégia. Resultado insuficiente ou negativo encerra a janela sem ajuste do modelo ou das regras.

## Escopo congelado

- Mercado e universo: Binance USD-M perpétuo, BTCUSDT e ETHUSDT, com uma posição global por vez. Não incluir BNB/SOL, Spot ou outro ativo neste ciclo.
- Dados para sinais: 01/09/2026 00:00 UTC até 27/09/2026 00:00 UTC, fim exclusivo. Carregar dados até 28/09/2026 00:00 UTC exclusivamente para maturar o horizonte máximo dos sinais.
- Elegibilidade temporal: um sinal precisa ocorrer em ou após 01/09 e antes de 27/09; a última janela de 1.440 minutos precisa terminar até 28/09 00:00 UTC. Não preencher lacunas nem criar preços sintéticos.
- Fonte: arquivos oficiais diários Binance Vision USD-M `klines` e `markPriceKlines`, com `.CHECKSUM` e integridade ZIP verificados, para ambos os símbolos de 01 a 27/09. Funding: endpoint oficial `GET /fapi/v1/fundingRate` em `[01/09, 28/09)` UTC, preservando o JSON bruto, horários, ordem e SHA-256. Como a resposta pode incluir `fundingTime` exatamente igual ao `endTime`, manter o payload bruto, mas mapear para o replay somente registros com timestamp estritamente menor que 28/09 00:00 UTC; registrar a linha de fronteira excluída. Qualquer dia ou minuto requerido ausente invalida a execução; não interpolar.
- Leitura dos arquivos diários: verificar e remover apenas o cabeçalho CSV oficial conhecido, conferir os nomes das 12 colunas e exigir 1.440 candles ordenados e únicos por dia após a leitura. Cabeçalho não conta como candle e nenhum candle de mercado pode ser descartado para satisfazer a contagem.
- Aquecimento e replay: combinar os novos dados apenas com o dataset BTC/ETH USD-M já verificado, que termina em 01/09/2026. Usar histórico anterior para indicadores causais e marcas de saída; a faixa de seleção permanece a definida acima.
- Scanner: copiar C06, sem alteração — breakout/continuação em 1m, lookback de 300m, volume mínimo 1,3× mediana móvel de 300m, cooldown de 15m por direção, contexto causal de 1h/4h, stop de 1 ATR15m, saída `trend_loss`, horizonte máximo de 1.440m.
- Treino: um único regressor XGBoost CUDA/hist mensal para setembro, com as 48 features C06, mesmos hiperparâmetros, target `net_return` usado pelo C06 e candidatos BTC/ETH. Treino exclusivamente sobre `candidate_labels.csv` C06 que satisfaçam `signal_time < 2026-08-31T00:00Z` e `label_end_time < 2026-09-01T00:00Z`, conforme a função de maturação/embargo C04. Exigir CUDA real e inferência CUDA; abortar sem fallback CPU.
- Seleção: score `predicted_net_return > 0,012`, estrito, sem alteração. Não calibrar ou escolher cortes após examinar setembro.
- Execução: usar o simulador C02/C06, capital inicial US$ 10.000, risco de 0,25% por trade e notional bruto limitado a 1,0× equity. Custo-base USD-M: taxa 5 bps e slippage 5 bps por lado; stress dobra ambos e mantém funding observado.
- Comparação: reportar todos os candidatos, scores, eventos selecionados, operações executadas, base/stress, funding, concentração por símbolo/semana, acerto, payoff, EV líquido, profit factor, PnL e drawdown. Separar candidatos selecionados de posições executadas pela restrição de posição única.
- Nenhuma ordem real será enviada; nenhum processo de paper ou configuração externa será iniciado ou alterado.

## Métricas e decisão

Manter os critérios da proposta pós-C12: EV-base líquido estritamente acima de 1,2% por operação, payoff pelo menos 1:1, profit factor pelo menos 1,25, no mínimo 200 trades completos em oito ou mais semanas e PnL agregado positivo sob stress. Acerto próximo de 70% é preferência; drawdown deve ser medido e minimizado entre estratégias aprovadas, sem teto fixo.

Como esta avaliação tem menos de quatro semanas, o gate de duração/amostra fica estruturalmente indisponível. Exibir todos os critérios mesmo assim, marcar a estratégia como não aprovada e não combinar esta janela com a amostra C06 de janeiro a agosto para simular independência ou completar o mínimo. Um resultado positivo mantém somente a hipótese para observação futura congelada; um resultado negativo não autoriza outro corte ou uma exclusão de mês/ativo.

## Integridade e artefatos

Antes de coletar dados, verificar ausência de todos estes destinos:

- Dataset adicional: `research/data/usdm_c17_sep_holdout_1m/`.
- Resultado: `research/results/cycle17_c06_sep_temporal_extension_2026-09-28/`.
- Runner temporário, removido após execução e verificação: `research/.tmp_c17_sep_temporal_extension.py`.
- Relatório: `research/docs/CICLO17_EXTENSAO_TEMPORAL_C06_SETEMBRO_RESULTADOS_2026-09-28.md`.

Registrar no ledger hashes do protocolo, runner, dataset C06 e manifesto, rótulos C06, códigos congelados e relatório-base antes da coleta. Registrar também todos os receipts diários e payloads de funding; preservar arquivos originais. Se uma execução falhar depois de expor métricas ou gerar saídas, registrar a falha e os hashes antes de qualquer retomada. Não sobrescrever artefatos existentes.

Uma retomada de coleta interrompida só pode reutilizar os arquivos parciais do próprio C17 depois de comparar o `.CHECKSUM` local ao receipt oficial atual e revalidar o SHA-256/CRC do ZIP. Não substituir nenhum arquivo existente; qualquer arquivo inesperado ou checksum divergente encerra a execução.

## Fontes locais

- Proposta e critérios: `research/docs/Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md`.
- Resultado/limites C06: `research/docs/CICLO06_MINUTE_BREAKOUT_STOP15M_RESULTADOS_2026-09-28.md`.
- Transferência e próximo passo: `research/docs/CICLO16_TRANSFERENCIA_C06_BNB_SOL_RESULTADOS_2026-09-28.md`.
- Implementação congelada: `research/scripts/cycle06_minute_breakout_stop15m.py`, `cycle04_rolling_refit.py`, `cycle03_direct_net_ev.py` e `cycle02_multiframe_research.py`.
- Dataset e labels-fonte: `research/data/usdm_btc_eth_1m/` e `research/results/cycle06_minute_breakout_stop15m_2026-09-28/`.

Nenhuma execução, coleta de dados ou ordem está autorizada pelo resultado histórico. Este protocolo autoriza apenas o replay retrospectivo aqui delimitado.
