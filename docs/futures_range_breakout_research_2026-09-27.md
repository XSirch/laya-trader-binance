# Resultado: rompimento da faixa de 60 minutos com fluxo

## Decisão

Sem candidata. O classificador ajustou com 11.460 eventos independentes de treino, mas nenhum evento da validação de 2025 recebeu probabilidade de vitória de pelo menos 0,55. Por isso, todos os oito limiares congelados, de 0,55 a 0,90, selecionaram zero operações. Não escolhi configuração nem usei 2026 para procurar outro limiar.

## Dados

O replay usou BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT perpétuos, com velas de um minuto e funding de janeiro/2024 a agosto/2026. Os 116.494 eventos brutos distribuem-se assim: 24.581 BTC, 31.630 ETH, 24.567 BNB e 35.716 SOL. A validação tem 44.522 eventos e a confirmação diagnóstica, sem seleção, 27.045. Os arquivos mensais locais tiveram seus checksums conferidos; nenhuma ordem ou chamada Jev foi enviada.

O gatilho exigiu rompimento do extremo anterior de 60 minutos, imbalance de takers alinhado de pelo menos 0,20 e volume de cinco minutos acima de 1,5 vezes a mediana. Stop foi colocado 0,1 ATR para dentro da faixa rompida, alvo bruto de 1,8R, prazo máximo de 60 minutos, custos de 0,10%/0,15% por lado e funding histórico. Entrada na abertura seguinte, stop primeiro em colisão, alocação fixa de 25% por par e sem alavancagem.

## Leitura

Esta regra não chegou a gerar operações avaliáveis no limiar mínimo de probabilidade; não existe acerto, payoff ou EV de trades selecionados para reportar. O resultado reprovou por baixa confiança do modelo e amostra operacional zero na validação. Não relaxei o limiar, porque isso seria selecionar um novo modelo depois de observar os resultados desta amostra.

Também medi o gatilho fixo sem ML, como controle. A regra-base gera muitas operações, mas tem EV negativo e acerto muito abaixo da meta:

| Período | Custo/lado | Trades | Acerto | Payoff líquido | EV líquido/operação | DD adverso |
|---|---:|---:|---:|---:|---:|---:|
| Validação 2025 | 0,10% | 12.095 | 33,78% | 0,597 | -0,202% | 6,11% |
| Validação 2025 | 0,15% | 12.095 | 27,30% | 0,416 | -0,302% | 9,13% |
| Confirmação diagnóstica 2026 | 0,10% | 7.227 | 33,75% | 0,590 | -0,195% | 3,52% |
| Confirmação diagnóstica 2026 | 0,15% | 7.227 | 26,62% | 0,410 | -0,295% | 5,33% |

Assim, não é somente um threshold ML alto que explica a ausência de entradas: o gatilho bruto também falha nos novos critérios.

O histórico foi usado em pesquisas com granularidade maior. Assim, os cortes temporais deste teste não são um holdout totalmente intocado. A conclusão limita-se à hipótese congelada e ao classificador fixo; não prova que todos os rompimentos em futuros falhem.

- Protocolo: [futures_range_breakout_protocol_2026-09-27.md](futures_range_breakout_protocol_2026-09-27.md).
- Relatório com hashes e todos os limiares: `results/futures_range_breakout_20260927/research.json`.
- SHA-256 do código: `1693598422a94c326bb10edb45de6d989ad67e726aab61a905ebe2fffd7c58b7`.
- SHA-256 do protocolo: `c51de1f3332a2e41e54281822450806ae328d1ae4dcf6edb5777a1bb9219beae`.
