# Resultado: absorção de fluxo agressor em futuros de 1 minuto

## Decisão

Hipótese rejeitada para negociação. O sinal entra contra fluxo agressor extremo quando o preço não o confirma. A regra não atingiu acerto, payoff nem EV das metas atuais. O classificador HistGradientBoosting ficou sem treino porque sobraram somente 41 eventos de treino após reduzir sobreposição, abaixo do mínimo congelado de 400. Portanto, os resultados abaixo são do gatilho fixo sem filtro ML; não atribuo habilidade ao modelo.

## Dados e execução

O replay usou BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT em contratos perpétuos USD-M, velas de 1 minuto de janeiro/2024 a agosto/2026. Foram lidos 1.402.560 minutos e 2.922 observações de funding por par. Os 128 arquivos mensais de candles foram conferidos pelo SHA-256 publicado e pela integridade CRC do ZIP. O funding foi debitado ou creditado nas posições atravessadas.

O treino contém 41 eventos após declustering de 60 minutos; validação contém 164 e confirmação diagnóstica contém 165. A validação fechou 116 operações e a confirmação 111. Os custos por lado foram 0,10% no cenário-base e 0,15% no estresse, incluindo taxas presumidas e slippage fixo. A entrada foi na abertura seguinte; stop/target simultâneos contam como stop primeiro; o limite foi uma posição por par, com alocação fixa de 25% do capital por par e sem alavancagem. Nenhuma ordem ou chamada Jev foi enviada.

## Métricas por operação

Acerto conta PnL líquido positivo. Payoff é ganho líquido médio dividido pela perda líquida média absoluta. EV é o PnL líquido médio dividido pelo notional comprometido na entrada. DD é a queda adversa da carteira com sleeves fixos de 25%.

| Período | Custo/lado | Operações | Acerto | Payoff líquido | EV líquido/operação | DD adverso | Retorno da carteira |
|---|---:|---:|---:|---:|---:|---:|---:|
| Validação 2025 | 0,10% | 116 | 28,45% | 0,306 | -0,232% | 6,82% | -6,73% |
| Validação 2025 | 0,15% | 116 | 13,79% | 0,176 | -0,332% | 9,70% | -9,63% |
| Confirmação diagnóstica jan–ago/2026 | 0,10% | 111 | 40,54% | 0,335 | -0,173% | 4,88% | -4,81% |
| Confirmação diagnóstica jan–ago/2026 | 0,15% | 111 | 23,42% | 0,173 | -0,273% | 7,60% | -7,59% |

As quatro linhas ficam abaixo de 70% de acerto, payoff 1:1 e EV +1,2%. Embora o DD isolado fique abaixo de 10% neste replay, isso não compensa a expectativa negativa. O estresse de custo reduz ainda mais acerto, payoff e EV.

## Limites e artefatos

O resultado não demonstra impossibilidade de outras estratégias. É uma rejeição desta hipótese com os limiares congelados. O histórico já foi examinado em outras resoluções no projeto; esta coleta de 1 minuto acrescenta granularidade, mas não é um holdout de mercado totalmente intocado. OHLC de 1 minuto não prova spread, fila ou fills reais, e o slippage é uma hipótese fixa.

- Protocolo congelado: [futures_flow_absorption_protocol_2026-09-27.md](futures_flow_absorption_protocol_2026-09-27.md).
- Relatório completo com hashes, arquivos de entrada e métricas: `results/futures_flow_absorption_20260927/research.json`.
- Operações do gatilho fixo: `results/futures_flow_absorption_20260927/static_signal_trades.csv`.
- Hash SHA-256 do código de pesquisa: `6ca143bf1593bd4159ad1b66fb0c8ffed20f234f744071666f07d7669dee14d2`.
- Hash SHA-256 do protocolo: `1c7c3371a105cada8dd30ae41b81ea3699a6a56b70f7142e5fa9e2491a8ca15d`.
