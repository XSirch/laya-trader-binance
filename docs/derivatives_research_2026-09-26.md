# Continuação: hedge, futuros direcionais e adaptação

Data: 26/09/2026. **Objetivo permanece ativo. As 18 novas hipóteses ainda não demonstraram lucratividade consistente.** Este documento registra progresso e evidências; não encerra a pesquisa nem aprova operação real.

## Dados adicionais

Foram obtidos 528 arquivos mensais oficiais Binance USD-M, de janeiro/2023 a agosto/2026: preços negociados, preços de marcação e pagamentos de funding de BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. Os arquivos de marcação omitem 24/02/2023 e 29/06/2026 nos quatro ativos. O carregador detectou as lacunas e recuperou os oito arquivos diários oficiais correspondentes, também conferidos por SHA256. Não houve interpolação.

Os 536 arquivos e hashes estão no [manifesto de fontes](derivatives_sources_2026-09-26.json). A marcação horária permite verificar funding e margem com mais evidência que usar somente candles spot. O timestamp real do funding é preservado e não pode entrar no indicador antes da publicação.

## Funding com hedge

O [protocolo](carry_protocol_2026-09-26.md) foi escrito antes dos resultados desta família. O simulador compra uma quantidade no spot e vende a mesma quantidade no perpétuo, limitando cada lado a 25% do patrimônio no rebalanceamento semanal. O restante permanece em dinheiro, disponível como margem. A carteira paga custos nas duas pernas, recebe funding positivo e paga funding negativo; não usa empréstimos ou rendimento fictício do caixa.

Foram comparadas quatro regras: carregar sempre, carregar com média de funding positiva, entrar acima de 8% anualizados e permanecer até a média ficar negativa, ou entrar somente acima de 15%. A média usa exclusivamente os 30 dias anteriores.

A regra selecionada pelo desenvolvimento de 2024 foi funding médio positivo. Ela não resistiu aos períodos posteriores. A regra com histerese de 8% teve resultado combinado positivo, mas não abriu posição ao iniciar a janela isolada de 2026. Reiniciar uma janela em caixa e manter uma posição desde uma janela anterior são experiências diferentes; o relatório apresenta ambas por meio dos períodos isolados e do replay combinado.

O funding não compensou de forma persistente os custos conservadores desta carteira. Mesmo um retorno positivo de algumas décimas percentuais não demonstraria, por si, vantagem sobre o custo de oportunidade e os riscos da corretora.

Evidência: [carry_research_2026-09-26.json](carry_research_2026-09-26.json).

## Posições compradas e vendidas

Foram fixadas dez hipóteses antes da execução: EMA 8/32, EMA 16/64, EMA 32/128, SMA 20/100, canais 20/10 e 55/20, momentum de 30 dias, combinação das três EMAs, combinação multifatorial e força relativa entre os quatro ativos.

O tamanho usa volatilidade histórica dos 30 dias anteriores, alvo de 20% anualizados por parcela e limite absoluto de 50% de exposição da parcela no rebalanceamento. O sinal vem do candle diário completo e é executado às 01h UTC seguintes, incorporando uma hora de atraso. O custo conservador é 0,15% por lado, além do funding efetivamente observado. O custo-base é 0,10% por lado. São hipóteses de taxas e execução, não condições verificadas em conta.

Retornos de janeiro/2025 a julho/2026, após custos conservadores e funding:

| Hipótese | Retorno combinado | Drawdown horário | Meses positivos |
|---|---:|---:|---:|
| EMA 8/32 | +11,71% | 14,40% | 9/19 |
| EMA 16/64 | +7,39% | 12,48% | 9/19 |
| EMA 32/128 | +13,98% | 14,36% | 10/19 |
| SMA 20/100 | +6,60% | 16,03% | 10/19 |
| Canal 20/10 | -8,67% | 15,74% | 8/19 |
| Canal 55/20 | -6,04% | 11,59% | 8/19 |
| Momentum 30 | +4,04% | 13,91% | 9/19 |
| Combinação de EMAs | +12,29% | 10,85% | 9/19 |
| Multifatorial direcional | +7,68% | 6,52% | 9/19 |
| Força relativa entre ativos | +4,18% | 5,74% | 11/19 |

A seleção usando apenas 2024 escolheu o canal 55/20, que perdeu nos períodos posteriores. Portanto, a EMA 32/128 não pode ser apresentada como seleção validada só porque tem o maior retorno posterior. O multifatorial teve drawdown menor, mas perdeu 5,50% em 2025 H1; a combinação de EMAs perdeu 5,05% nessa janela. Nenhuma passou nos critérios de consistência nas três janelas posteriores.

Evidência: [directional_research_2026-09-26.json](directional_research_2026-09-26.json).

## Adaptação usando somente resultados anteriores

Quatro políticas combinaram as dez hipóteses com caixa: pesos com base em 63 ou 126 dias passados, com e sem exigência de evidência positiva mínima antes da alocação. Os pesos foram calculados com os retornos líquidos históricos dos modelos, já descontados os custos conservadores e o funding. A avaliação conhecida mais recente é de meia-noite; a nova exposição é executada às 01h.

As combinações de 63 e 126 dias retornaram +2,12% e +0,52%, respectivamente. Com a exigência adicional de evidência mínima, retornaram -0,92% e -2,41%. A seleção pelo desenvolvimento de 2024 escolheu a política de abstenção de 63 dias, que também não passou depois. Adaptar pesos reduziu alguns riscos, mas não resolveu a inconsistência.

Evidência: [adaptive_research_2026-09-26.json](adaptive_research_2026-09-26.json). O registro completo dos pesos está em `results/adaptive_weights.json`; as curvas diárias intermediárias ficam nos relatórios locais e são retiradas apenas das cópias compactas versionadas.

## Validação e limites

Os testes verificam sinais dos fluxos de funding, custos das duas pernas, neutralização de movimentos de preço com quantidades iguais, exclusão de pagamentos no instante da entrada/saída, ausência de influência de dados futuros, controle de exposição e temporalidade dos pesos adaptativos.

Foi usada uma margem mínima de 10% do nocional como stress. Isso não substitui as faixas reais de manutenção, liquidação, ADL, regras de colateral ou a elegibilidade da conta. Pagamentos usam o preço de marcação na abertura da hora, enquanto o evento real pode ocorrer alguns milissegundos depois. Rebalanceamentos e fills são aproximações; spreads e simultaneidade das pernas ainda precisam de evidência executável. Nenhuma conta de futuros foi conectada e nenhuma ordem foi enviada.

Todos os períodos de 2025–2026 desta rodada já foram examinados em outras famílias. O próximo trabalho precisa ampliar a diversidade de ativos e regimes históricos e manter seleção temporal, em vez de ajustar repetidamente parâmetros aos mesmos meses. A confirmação prospectiva permanece pendente.

## Reprodução

```powershell
uv run python -m jev_trader.derivatives_data
uv run python -m jev_trader.carry
uv run python -m jev_trader.directional
uv run python -m jev_trader.adaptive
uv run python -m unittest discover -s tests -v
uv run python scripts/snapshot_research.py
uv run python scripts/check_encoding.py
```

Não houve novas chamadas JEV nesta etapa. O contrato continua: JEV pontua aderência aos critérios em uma única chamada com todos os indicadores, e o script decide a exposição.

Fontes primárias consultadas: [arquivos públicos Binance](https://github.com/binance/binance-public-data/), [funding com hedge spot/futuros](https://www.binance.com/en-AE/support/faq/detail/61012e690cf343e7979649282a2ccc3c) e [limitações de execução e liquidação da estratégia](https://www.binance.com/en-AE/support/faq/detail/f330e17d6fc04679b9b21d6f9350e787).
