# Pesquisa: reversão relativa entre pares de futuros cripto

## Resultado

**Reprovada na validação de 2025.** O sinal de cruzamento do z-score do spread `ln(A/B)`, sem filtro de ML, gerou 2.765 operações selecionadas pelo limite de sobreposição/cooldown. No custo base, acertou 20,58%, com payoff líquido de 0,701 e EV de -0,189% por operação sobre o notional bruto combinado das pernas. No custo de estresse, acertou 12,08%, payoff 0,603 e EV -0,289%. Nenhum dos limiares HGB pré-definidos entre 0,55 e 0,90 selecionou uma operação em 2025; portanto, não existe candidato a levar à confirmação.

O recorte janeiro–agosto/2026 fica apenas como diagnóstico estático da regra, sem seleção nem ajuste. Teve 1.862 operações, acerto de 13,00% e EV -0,190% no custo base; no estresse, 5,64% e -0,290%. Não foi aplicado um limiar ML porque a validação de 2025 falhou.

| Recorte sem filtro de ML | Operações | Acerto base / estresse | Payoff base / estresse | EV líquido por operação base / estresse | DD adverso base / estresse |
|---|---:|---:|---:|---:|---:|
| Validação, 2025 | 2.765 | 20,58% / 12,08% | 0,701 / 0,603 | -0,189% / -0,289% | 130,63% / 199,76% |
| Diagnóstico, jan–ago/2026 | 1.862 | 13,00% / 5,64% | 0,591 / 0,538 | -0,190% / -0,290% | 88,38% / 134,92% |

Todos os gates falharam. O drawdown pode superar 100% neste replay porque a curva soma retornos não compostos com alocação fixa de 25% do patrimônio inicial por operação; isso sinaliza ruína no modelo de alocação e não deve ser lido como uma curva de conta com stop automático em saldo zero.

## Protocolo executado

- Universo fixo: BTC/ETH, BTC/BNB, BTC/SOL, ETH/BNB, ETH/SOL e BNB/SOL, perpétuos USD-M em candles de um minuto e funding histórico local de janeiro/2024 a agosto/2026.
- O z-score usou média e desvio dos 1.440 spreads anteriores, sem incluir o fechamento do sinal. Entrada na abertura seguinte; alvo/stop ativados pelo fechamento de um minuto e executados na abertura subsequente; saída temporal na abertura após 60 minutos. Aberturas reais determinam o preço, inclusive gaps.
- PnL usa os retornos realizados de cada perna com notional igual, funding efetivamente observado, e custo de 0,10%/0,15% por ordem em cada perna, equivalentes a 0,20%/0,30% do notional bruto combinado na operação completa. Drawdown intratrade usa o extremo combinado adverso das duas pernas.
- Alocação fixa de 25% do patrimônio inicial por spread, sem alavancagem. Sinais simultâneos que compartilham ativo são descartados; cooldown de 30 minutos por ativo após saída.
- HGB classificou PnL líquido positivo no custo base. Treino em 2024: 3.187 eventos após declustering de 60 minutos e separação de eventos que compartilham ativos. Seleção de threshold exclusivamente em 2025, em passos de 0,05 de 0,55 a 0,90. A confirmação não foi usada para procurar parâmetros.
- Houve 40.476 cruzamentos antes dos filtros temporais e de execução. Os candles e arquivos de funding foram verificados por SHA-256 e CRC; 128 arquivos de candles e 128 de funding.

## Interpretação e próxima hipótese

Um z-score móvel de 24 horas sobre razões de preço não demonstrou reversão útil: mesmo sem ML, o acerto ficou muito abaixo de 70%, payoff abaixo de 1 e EV negativo depois dos custos. O classificador não selecionou nenhum sinal acima dos limiares congelados. Não alterar janela, z-score, pares ou threshold olhando 2026.

Esta pesquisa não autoriza uso real. A próxima linha deve formular uma hipótese separada, com regra e validação congeladas antes de calcular os resultados; não é uma otimização deste spread.

## Artefatos e proveniência

- Protocolo congelado: [cross_asset_spread_protocol_2026-09-27.md](cross_asset_spread_protocol_2026-09-27.md)
- Implementação: [cross_asset_spread_research.py](../src/jev_trader/cross_asset_spread_research.py)
- Resultado detalhado, manifestos e métricas: [research.json](../results/cross_asset_spread_20260927/research.json)
- Trades e escores diagnósticos: [static_signal_trades.csv](../results/cross_asset_spread_20260927/static_signal_trades.csv)
- SHA-256 do protocolo: `ce295d0e59bd0cde18641179bda2480f732248a8054f91a0662b102dbbc404ad`
- SHA-256 do código: `eb32cf8c7a3217149f1e3c83f86f8f54541b4e199574acb0723ab05ca73f0be7`
- Nenhuma ordem foi enviada e nenhuma chamada Jev foi feita neste replay.
