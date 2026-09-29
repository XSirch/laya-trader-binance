# Resultado: continuação de fluxo em futuros de 1 minuto

## Decisão

Sem candidata. A regra congelada exigia desequilíbrio de takers e retorno de cinco minutos na mesma direção, além de volume cotado acima de 1,5 vezes a mediana recente. O HGB treinou, mas nenhum limiar entre 0,55 e 0,90 passou as metas na validação de 2025. Não selecionei limiar nem resultado de confirmação de 2026.

## Dados e modelo

Foram reutilizados os mesmos 128 arquivos de velas USD-M Futures de um minuto, com checksums já conferidos, mais o funding histórico para BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. Cada par contém 1.402.560 candles e 2.922 pontos de funding. O gerador encontrou 16.781 eventos brutos: 3.408 em BTC, 2.904 em ETH, 7.664 em BNB e 2.805 em SOL.

Após reduzir eventos de treino sobrepostos por 60 minutos, restaram 2.625 para ajustar o classificador, com 808 resultados líquidos positivos no cenário-base. A validação contém 6.742 eventos e a confirmação diagnóstica, sem seleção, 4.777. O HGB usou as 14 features causais e os hiperparâmetros congelados no protocolo. Uma primeira execução parou por restrição local do Windows ao criar threads; repetir com limite de uma thread concluiu o mesmo modelo e os mesmos dados.

## Resultado da validação

| Limiar ML | Operações selecionadas | Acerto base/estresse | Payoff base/estresse | EV líquido base/estresse | Resultado |
|---:|---:|---:|---:|---:|---|
| 0,55 | 7 | 42,86% / 42,86% | 0,885 / 0,559 | -0,092% / -0,192% | Reprovado |
| 0,60–0,90 | 0 em cada limiar | Sem amostra | Sem amostra | Sem amostra | Reprovado por amostra insuficiente |

O menor limiar testado produziu menos de 30 operações e ficou abaixo de 70% de acerto, payoff 1:1 e EV líquido superior a 1,2%. Como a validação falhou, não foi feita seleção usando janeiro–agosto/2026. Nenhuma ordem ou chamada Jev foi enviada.

O gatilho fixo sem filtro ML também foi medido, como controle previamente definido:

| Período | Custo/lado | Trades | Acerto | Payoff líquido | EV líquido/operação | DD adverso |
|---|---:|---:|---:|---:|---:|---:|
| Validação 2025 | 0,10% | 3.214 | 30,74% | 0,633 | -0,186% | 1,49% |
| Validação 2025 | 0,15% | 3.214 | 23,43% | 0,440 | -0,286% | 2,30% |
| Confirmação diagnóstica 2026 | 0,10% | 2.278 | 28,45% | 0,585 | -0,193% | 1,10% |
| Confirmação diagnóstica 2026 | 0,15% | 2.278 | 20,85% | 0,376 | -0,293% | 1,67% |

O controle confirma que a direção da regra-base também falha; o filtro ML não foi a única causa de reprovação.

## Limites e reprodução

Esta é uma hipótese diferente da absorção: a direção da posição acompanha a confirmação de preço e fluxo. As duas usam candles históricos já vistos em outras pesquisas; o corte temporal não é um holdout de mercado intocado. A análise não prova execução real nem inviabilidade de outras estratégias.

- Protocolo congelado: [futures_flow_continuation_protocol_2026-09-27.md](futures_flow_continuation_protocol_2026-09-27.md).
- Relatório completo, thresholds, hashes e arquivos de origem: `results/futures_flow_continuation_20260927/research.json`.
- Hash SHA-256 do código: `f8d490d6414bf9f39599098c26ba8331c56bdb399bd9f10d05fb977b67c0b928`.
- Hash SHA-256 do protocolo: `a5f77c09cdaa551d2368b5ece6a8796124469029b0b509bf0f3cdec68c3e29a0`.
