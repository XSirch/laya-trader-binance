# Pesquisa: momentum cross-sectional entre futuros cripto

## Resultado

**Reprovada na validação de 2025.** A regra fixa comprou o contrato líder em retorno dos últimos 60 minutos e vendeu o retardatário quando o líder estava positivo, o retardatário negativo e a distância superava 0,75%. O hold foi de 60 minutos.

| Recorte sem filtro de ML | Operações | Acerto base / estresse | Payoff base / estresse | EV líquido por operação base / estresse | DD adverso base / estresse |
|---|---:|---:|---:|---:|---:|
| Validação, 2025 | 1.978 | 23,05% / 15,52% | 0,814 / 0,717 | -0,201% / -0,301% | 99,35% / 148,80% |
| Diagnóstico, jan–ago/2026 | 473 | 17,34% / 9,73% | 0,769 / 0,704 | -0,197% / -0,297% | 23,38% / 35,15% |

O HGB treinou com 2.800 eventos independentes de 2024; nenhum threshold entre 0,55 e 0,90 selecionou operação em 2025. Como a validação não passou, o recorte de 2026 permaneceu um diagnóstico estático, sem seleção de threshold ou parâmetros.

Nenhum gate passou. A queda superior a 100% resulta da curva não composta que repete notional fixo de 25% do capital inicial, sem stop de negociação por saldo; representa ruína dentro desse modelo de alocação, não uma curva limitada a saldo zero.

## Protocolo executado

- Universo fixo BTC, ETH, BNB e SOL em perpétuos USD-M, dados de um minuto e funding histórico de janeiro/2024 a agosto/2026. Ordenação a cada 15 minutos UTC; gatilho, hold, custos e features constam em [protocolo congelado](cross_sectional_momentum_protocol_2026-09-27.md).
- PnL calculado pelas duas pernas reais com notional igual, funding observado e custos de 0,10%/0,15% por ordem em cada perna, totalizando 0,20%/0,30% do notional combinado por round trip. Notional bruto fixo de 25% do capital inicial, sem alavancagem. Sem stop ou alvo intraperíodo nesta regra.
- HGB classifica PnL líquido positivo no custo base; treino 2024, threshold escolhido apenas em 2025 e confirmação apenas após eventual validação. Treino exigia 400 eventos, validação e confirmação 100 trades; gates simultâneos de acerto >=70%, payoff >=1, EV >1,2% por operação e DD <=10% em ambos os custos.
- Foram gerados 10.788 eventos candidatos; 4.392 na validação e 869 no período de confirmação. 128 arquivos de candles e 128 de funding foram verificados via SHA-256/CRC.
- Nenhuma ordem foi enviada e nenhuma chamada Jev foi feita.

## Interpretação

A ordenação de retornos de uma hora não antecipou continuação relativa suficiente para superar custos. O acerto fixo ficou em 23,05% no custo base; o EV foi -0,201%. O HGB não identificou sinais com probabilidade acima do menor threshold congelado. Não ajustar o gap de 0,75%, o horizonte de 60 minutos, a cadência ou os thresholds olhando 2026.

Esse período histórico já foi examinado em outras pesquisas e não é evidência prospectiva. Esta hipótese não é candidata para operação real. Uma pesquisa seguinte precisa formular outra fonte de edge e congelar regras antes da avaliação.

## Artefatos

- [Implementação](../src/jev_trader/cross_sectional_momentum_research.py)
- [Métricas e manifestos completos](../results/cross_sectional_momentum_20260927/research.json)
- [Operações diagnósticas](../results/cross_sectional_momentum_20260927/signal_trades.csv)
- SHA-256 do protocolo: `f259aa1c2ff58e193e564a5606f6fe319bd638ab3100bcc77d6e8cb552b5028c`
- SHA-256 do código: registrado no manifesto JSON.
