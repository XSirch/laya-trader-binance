# Ciclo 17 — extensão temporal congelada do C06 em setembro

Execução: 2026-09-28T23:36:31.951938+00:00
Status: **não aprovado**; janela retrospectiva exploratória e curta demais para os gates de consistência.

## Decisão

O C17 pontuou setembro com um refit mensal treinado apenas em rótulos maduros antes de 01/09/2026. Scanner, features, saída, risco, custos e corte estrito `> 0,012` ficaram congelados. A janela não satisfaz oito semanas ativas e não pode aprovar a estratégia, mesmo se as métricas econômicas forem positivas.

A janela compartilha dados de mercado com outras análises de setembro. Portanto, o resultado não é holdout global independente nem validação prospectiva. Não houve ajuste após observar os resultados e nenhuma ordem real foi enviada.

## Métricas executáveis

EV é o retorno líquido médio por trade executado sobre o nocional inicial. A carteira tem uma posição global; eventos selecionados que conflitam com uma posição aberta não contam como operações.

| Métrica | Base | Stress |
|---|---:|---:|
| Operações executadas | 3 | 3 |
| Acerto | 0.00% | 0.00% |
| Payoff | n/a | n/a |
| EV líquido médio | -0.4862% | -0.6522% |
| Profit factor | 0.0000 | 0.0000 |
| PnL | US$ -52.97 | US$ -54.86 |
| Drawdown máximo | 0.65% | 0.64% |
| Semanas ativas | 2 | 2 |

Candidatos pontuados: 203; selecionados pelo corte congelado: 5; eventos selecionados completos: 5.

### Gates registrados

- EV-base > 1,2%: `False`.
- Payoff-base >= 1: `False`.
- Profit factor-base >= 1,25: `False`.
- PnL stress positivo: `False`.
- 200 trades e oito semanas: `False` (a janela contém 3 trades e 2 semanas ativas).
- Falhas calculadas pelo gate do simulador: `base_trades_below_200, base_active_weeks_below_8, base_ev_not_above_1_2_percent, base_payoff_below_1, base_profit_factor_below_1_25, stress_not_positive`.
- Acerto próximo a 70% continua preferência, não piso; drawdown foi medido sem teto.

## Método e proveniência

- Sinais: `2026-09-01T00:00:00+00:00` até `2026-09-27T00:00:00+00:00` UTC; buffer de desfecho até `2026-09-28T00:00:00+00:00`.
- Treino: 6406 labels C06 maduros até 2026-09-01T00:00:00+00:00; XGBoost xgboost_cuda em CUDA/hist; sem labels de setembro.
- Modelo: `research/results/cycle17_c06_sep_temporal_extension_2026-09-28/models/2026-09.json`, SHA-256 `b1c2d561a81a442b6a01afc77794d77cc81f4fee090e1ef02b87f21e8a1cdf6c`.
- Dados adicionais: `research/data/usdm_c17_sep_holdout_1m/candles.csv.gz`, SHA-256 normalizado `79b48fe0680eb09d6141d16182cd11a7d238877fb75ee501c08d070d1ba04208`; manifesto SHA-256 `ff8540b5337465cb828f4a21361da64f10a27b8380f83e7127cdb7982393da78`.
- Dataset/manifesto-base C06 SHA-256: `cd09bd04a01c7de294438415df17fb26f86d346f10fc1c21ececbb4de0d84691` / `370539d1379221bb5a5cdbbb2ff9de30530616cd82b1b638c58f136110f651f4`.
- Receipts oficiais, arquivos `.CHECKSUM`, contagens diárias e payloads brutos de funding ficam no manifesto/diretório de dados.
- Stress dobra taxas e slippage; funding observado permanece aplicado. Nenhuma ordem real foi enviada.

## Artefatos

- Protocolo SHA-256: `9355182a0b87555102ef37dad3afeef02e10fd143ed2e0d6decd14e2a2b828ab`.
- Relatório JSON: `research/results/cycle17_c06_sep_temporal_extension_2026-09-28/research.json` (hash final no ledger de experimentos).
- Relatório Markdown: `research/docs/CICLO17_EXTENSAO_TEMPORAL_C06_SETEMBRO_RESULTADOS_2026-09-28.md`.
- Runner SHA-256: `4ecbe7d7fd8415ce32bcfe2bedf9972ce94d017b052d06db7131ce14777d789c`; o arquivo temporário foi removido após a verificação.
- CSVs de scores, desfechos de candidatos selecionados e trades base/stress estão junto ao relatório JSON.

## Limite e próxima evidência

Este ciclo adiciona uma janela temporal posterior ao C16, mas não alcança a duração nem a amostra exigidas, e a janela já foi explorada com outras regras. Preservar seus scores e desfechos sem mudar o corte. Qualquer continuação precisa usar um período futuro congelado e acumulado separadamente; não somar meses conhecidos para declarar aprovação retrospectiva.
