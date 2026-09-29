# Ciclo 11 — resultados da extensão de `rank_blend`

Executado em 28/09/2026 conforme o protocolo congelado. Status: `recent_extension_failed`; a regra histórica não se manteve na janela recente. Nenhuma feature, peso, sinal ou limite foi alterado.

## Resultado por custo

O período vai de 01/08/2026 até 26/09/2026 00:00 UTC e contém oito semanas ativas. A contabilidade por episódio reconciliou com o replay de carteira diário do projeto.

| Custo por lado | Operações | Acerto | Payoff | EV por operação | Profit factor | Retorno da carteira | Drawdown |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0,10% (base) | 21 | 42,86% | 0,430 | −8,233% | 0,322 | −13,856% | 14,349% |
| 0,15% (estresse anterior) | 21 | 42,86% | 0,423 | −8,341% | 0,317 | −14,026% | 14,497% |
| 0,20% (custo dobrado) | 21 | 42,86% | 0,415 | −8,448% | 0,312 | −14,196% | 14,644% |
| 0,30% (estresse severo) | 21 | 38,10% | 0,490 | −8,662% | 0,301 | −14,534% | 14,939% |

Nenhum nível passou EV, payoff ou profit factor; o resultado também ficou negativo sob custo dobrado. A amostra é curta e não serve para afirmar a expectativa de longo prazo, mas a queda grande e consistente ao longo de oito semanas basta para **parar de priorizar `rank_blend`**. Não ajustar pesos ou limiares sobre essa janela.

## O que aprendemos sem apagar o histórico

Até julho, `rank_blend` tinha 252 episódios, EV +2,850% e payoff 1,031 a 0,15% por lado; validação e confirmação também eram positivas. O novo resultado não invalida essa medição anterior. Ele mostra mudança de regime ou fragilidade temporal: entre agosto e setembro, 21 episódios perderam em média −8,341% cada no mesmo custo. A regra era semanal e multiativo; esse sinal histórico não demonstrava uma fórmula de entrada intrahora.

Assim, mantemos a regra e o ledger como referência histórica, mas a classificamos como não consistente com a extensão recente. O antigo composto de baixa volatilidade + carry continua rejeitado separadamente: sua própria extensão perdeu 4,59%, e não deve ser confundido com `rank_blend`.

## Dados e limites

- 54 snapshots REST locais foram verificados; a sobreposição confirmou 864 candles e 54 registros de funding com os arquivos históricos.
- O universo continha os 20 contratos perpétuos históricos do experimento, incluindo ativos encerrados; não houve proxy de saída não resolvido nesta extensão.
- EV é calculado sobre nocional bruto inicial de cada episódio; o retorno e o drawdown são medidos sobre patrimônio da carteira.
- A janela já havia sido examinada para outra regra e a candidata foi selecionada após conhecer os resultados históricos até julho. É uma extensão retrospectiva exploratória, não um holdout independente ou paper prospectivo.
- Não houve treinamento de ML nem envio de ordem real.

Protocolo: [Ciclo 11](CICLO11_RANK_BLEND_EXTENSION_PROTOCOLO.md). Script: [broad_rank_blend_extension.py](../../src/jev_trader/broad_rank_blend_extension.py). Ledger e proveniência: `research/results/cycle11_rank_blend_extension_2026-09-28/`.
