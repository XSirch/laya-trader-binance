# Pesquisa: reclaim da VWAP a favor da tendência

## Resultado

**Reprovada na validação de 2025.** A regra operou o reclaim da VWAP móvel de 60 minutos na direção da EMA200 de 15 minutos, com volume relativo >=1,5, stop de 1 ATR, alvo de 1,5 ATR e hold máximo de uma hora.

| Recorte sem filtro de ML | Operações | Acerto base / estresse | Payoff base / estresse | EV líquido por operação base / estresse | DD adverso base / estresse |
|---|---:|---:|---:|---:|---:|
| Validação, 2025 | 8.829 | 14,71% / 7,16% | 0,579 / 0,518 | -0,211% / -0,311% | 465,98% / 686,70% |
| Diagnóstico, jan–ago/2026 | 6.528 | 11,49% / 4,95% | 0,530 / 0,446 | -0,200% / -0,300% | 326,80% / 489,99% |

O HGB treinou com 7.494 operações declusterizadas de 2024. Nenhum threshold de 0,55 a 0,90 selecionou operação em 2025, então 2026 ficou como diagnóstico fixo e não foi usado para ajustar o modelo.

Os drawdowns acima de 100% resultam da soma não composta com notional fixo de 25% do capital inicial, sem encerrar a simulação ao chegar a saldo zero. Eles indicam ruína no replay de alocação, mas não representam saldo de conta abaixo de zero numa corretora.

## Protocolo executado

- Perpétuos USD-M BTC, ETH, BNB e SOL; velas de 1 minuto e funding entre janeiro/2024 e agosto/2026. Entrada na abertura após o cruzamento; stop/alvo usam a faixa da vela, stop primeiro se ambos forem tocados e execução conservadora em gaps. Saída temporal após 60 minutos.
- Volume relativo comparado à mediana de 144 observações anteriores, uma por minuto, da janela móvel de volume de cinco minutos. A EMA200 usa candles de 15 minutos completos e descarta cinco spans iniciais de aquecimento.
- Notional fixo de 25% por operação, sem alavancagem; cooldown por ativo de 30 minutos. Custo por ordem de 0,10% base ou 0,15% estresse; custo completo de ida e volta de 0,20%/0,30% sobre o notional comprometido. PnL inclui funding.
- Features HGB: tendência EMA, VWAP, volume, imbalance, ATR, volatilidade, retornos e RSI14. Treino 2024, threshold congelado por validação 2025, confirmação apenas se a validação passasse. Nenhuma ordem nem chamada Jev foi feita.
- 34.015 eventos foram gerados; 12.522 no recorte de validação e 9.347 na confirmação. Arquivos de candles e funding passaram SHA-256/CRC: 128 de cada tipo.

## Interpretação

O cruzamento de VWAP a favor da tendência não produziu continuação confiável nesse universo e período. O acerto ficou em 14,71% e o EV em -0,211% no custo base; nenhum threshold ML congelado encontrou um conjunto elegível. Não ajustar VWAP, EMA, volume, ATR, alvo/stop ou threshold olhando o período de 2026.

O replay é histórico e não demonstra consistência prospectiva nem autoriza negociação real.

## Artefatos

- [Protocolo congelado](vwap_pullback_protocol_2026-09-27.md)
- [Implementação](../src/jev_trader/vwap_pullback_research.py)
- [Métricas e manifestos](../results/vwap_pullback_20260927/research.json)
- [Operações diagnósticas](../results/vwap_pullback_20260927/signal_trades.csv)
- SHA-256 do protocolo: registrado no manifesto JSON.
- SHA-256 do código: registrado no manifesto JSON.
