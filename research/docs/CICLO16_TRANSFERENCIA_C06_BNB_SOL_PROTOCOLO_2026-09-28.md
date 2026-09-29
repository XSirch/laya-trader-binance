# C16 — Transferência congelada do C06 para BNB e SOL

Data: 28/09/2026  
Status: pré-registro; executar apenas depois de registrar o hash do protocolo e do runner no ledger.

## Pergunta

O score direto do C06, treinado cronologicamente em BTCUSDT e ETHUSDT USD-M, preserva valor econômico quando aplicado sem retreino a BNBUSDT e SOLUSDT? A inclusão desses contratos acrescenta operações úteis ao mesmo portfólio USD-M com uma posição global?

## Justificativa e limite de novidade

Os estudos anteriores listados na proposta após o C12 incluíram BTC e ETH, mas não essa transferência de modelo para BNB e SOL. O universo foi fixado nesses dois contratos antes de calcular resultados, por serem os outros ativos com histórico local de candles USD-M de 1 minuto. Não haverá ranking ou seleção de ativos por retorno observado.

O teste usa a janela de janeiro a agosto de 2026, já examinada em estudos com BTC/ETH. Os retornos de BNB/SOL não foram usados nos experimentos C05, C06, C12, C13, C14 ou C15, mas o período é histórico e a transferência não é validação prospectiva independente. Um resultado favorável ainda exigiria observação futura congelada.

## Protocolo congelado

- Mercado: Binance USD-M; universo do portfólio combinado: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. A análise de transferência isolada usa somente BNBUSDT e SOLUSDT.
- Período de seleção: 02/01/2026 00:00 UTC até 01/09/2026 00:00 UTC, fim exclusivo. Sinais a partir de 31/08/2026 00:00 UTC são censurados para garantir maturação do horizonte de 1.440 minutos.
- Dados novos: candles de 1 minuto de 01/11/2025 até 01/09/2026 UTC, com OHLC de mark price de 1 minuto e funding observado. Os meses completos de candle, mark e funding devem passar SHA-256 e integridade ZIP do arquivo público oficial da Binance. Recuperação de mark ausente só pode usar arquivo diário oficial verificado; lacunas não recuperáveis encerram a execução sem preenchimento sintético.
- Aquecimento: novembro e dezembro de 2025 ficam fora da seleção e servem à inicialização causal dos indicadores de 1h/4h, EMA200, ATR de 15m e scanner. A validação temporal de candles deve permanecer estritamente contínua.
- Scanner e risco: copiar o C06 sem mudança: rompimento/continuação de 1 minuto, rompimento de máxima/mínima em 300 minutos, volume mínimo de 1,3 vezes a mediana móvel de 300 minutos, cooldown de 15 minutos por direção, contexto causal de 1h/4h, stop de 1 ATR calculado em 15 minutos, saída `trend_loss`, horizonte máximo de 1.440 minutos.
- Modelo: usar, por mês de seleção, o artefato XGBoost CUDA/hist correspondente salvo em C06 (2026-01 até 2026-08). Nenhum treino, calibração, ajuste de features ou atualização de modelo com BNB/SOL. A ordem e os nomes das 48 features devem coincidir com os modelos C06.
- Corte: selecionar exclusivamente quando a previsão direta de retorno líquido superar estritamente `0,012`. Não testar outro corte, faixa, direção, janela ou regra de saída.
- Reconciliação prévia: carregar os modelos salvos e reaplicar suas previsões a todos os candidatos BTC/ETH do C06. Cada score deve reconciliar com `walk_forward_scores.csv` dentro de erro absoluto máximo de `1e-8`. O replay BTC/ETH deve reconciliar todas as métricas base e stress do relatório C06 dentro de `1e-9`. Em caso de divergência, abortar a comparação de transferência.
- Replay: usar o mesmo simulador minuto a minuto C02/C06, uma posição global por vez, capital inicial de US$ 10.000, fração de risco de 0,25% por operação e notional bruto limitado a 1,0x do equity. Taxa-base USD-M de 5 bps e slippage de 5 bps por lado; o stress dobra taxa e slippage e mantém o funding observado. Não aumentar alavancagem ou risco.
- Saídas: reportar o portfólio BNB/SOL, o controle BTC/ETH reconciliado e o portfólio combinado de quatro contratos. Mostrar métricas base e stress, seleção e execução, EV líquido, acerto, payoff, profit factor, lucro, drawdown máximo, semanas ativas, distribuição por contrato, funding e razões de saída. Métricas por contrato são diagnósticas e não substituem o replay com uma posição global.

## Critérios registrados antes do resultado

Avaliar os gates para o portfólio BNB/SOL e para o portfólio de quatro contratos, separadamente, sem combinar os resultados entre portfólios:

1. Pelo menos 200 operações completas e não duplicadas em pelo menos oito semanas ativas.
2. EV-base líquido por operação, sobre o notional inicial, estritamente acima de 1,2%.
3. Payoff-base de pelo menos 1:1 e profit factor-base de pelo menos 1,25.
4. PnL agregado positivo no stress de taxas e slippage dobrados.

Taxa de acerto próxima de 70% é preferência flexível; não é piso. Não há teto fixo de drawdown: medi-lo e minimizá-lo somente entre variantes que passem os gates registrados. Mostrar concentração em eventos, semanas e ativos; retornos raros não serão removidos para melhorar as métricas.

Se a contagem ou qualquer outro gate falhar, encerrar C16 sem ajustar o seletor à janela avaliada. Se passar, ainda não declarar consistência nem autorização para ordens: preparar avaliação prospectiva apenas com regras congeladas. Nenhuma ordem real será enviada.

## Artefatos previstos

- Dados normalizados e manifestos: `research/data/usdm_c16_bnb_sol_1m/`.
- Resultado: `research/results/cycle16_frozen_c06_transfer_2026-09-28/`.
- Runner temporário, excluído depois da execução: `research/.tmp_c16_frozen_transfer_runner.py`.
- Relatório: `research/docs/CICLO16_TRANSFERENCIA_C06_BNB_SOL_RESULTADOS_2026-09-28.md`.
- Registro do protocolo, hashes do runner/modelos/fontes e resultado: `research/EXPERIMENTS.jsonl`.

## Fontes de implementação e dados

- Regras e gates: `research/docs/Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md`.
- Scanner, simulador e gerador de features: `research/scripts/cycle02_multiframe_research.py` e `research/scripts/cycle06_minute_breakout_stop15m.py`.
- Modelos, scores, labels, manifestos e métricas BTC/ETH: `research/results/cycle06_minute_breakout_stop15m_2026-09-28/` e `research/data/usdm_btc_eth_1m/`.
- Baixador, verificador de checksums e validador de candles: `research/src/binance_multistrategy/data.py`.
- Dados de mercado primários: arquivos públicos oficiais Binance Vision USD-M; cada arquivo usado deve ter receipt e SHA-256 no manifesto gerado.
