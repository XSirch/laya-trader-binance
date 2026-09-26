# Triagem da receita de funding no universo histórico de vinte ativos

Nenhum dos doze cenários atingiu receita anualizada de 50%, mesmo antes de custos e com hedge idealizado. No período de janeiro de 2024 a 26 de setembro de 2026, o melhor índice de receitas chegou a 10,2031% ao ano com notional equivalente a todo o patrimônio. Isso desprioriza estes seletores de funding para a meta solicitada de retorno líquido anual de 50% e drawdown máximo de 10%. A triagem não é um backtest de carteira e não prova a impossibilidade de obter esse retorno com outras estratégias.

O [protocolo](funding_capacity_protocol_2026-09-26.md), simulador, testes e executor foram registrados no commit `792b842` antes da avaliação. O processo terminou com código zero em 29,69 segundos. [Resultados compactos](funding_capacity_research_2026-09-26.json); auditoria completa em `results/funding_capacity_research.json`; entradas fixadas em `results/funding_capacity_inputs.json`.

Os valores abaixo são CAGR do **índice de receitas de funding**, sem custos, diferença de preço spot/perp, juros, margem ou liquidação. Não são rentabilidade líquida da carteira. A proporção corresponde ao notional vendido em futuros dividido pelo índice, continuamente reajustado sem custo por hipótese.

| Regra fixada | Proporção | 2022–2023 | Jan/2024–26/set/2026 |
|---|---:|---:|---:|
| Cinco maiores médias positivas de 30 dias | 0,5 | 3,8659% | 4,3775% |
| Cinco maiores médias positivas de 30 dias | 1,0 | 7,8808% | 8,9462% |
| Cinco mais persistentes entre 7 e 30 dias | 0,5 | 3,8316% | 4,3246% |
| Cinco mais persistentes entre 7 e 30 dias | 1,0 | 7,8097% | 8,8357% |
| Maior média positiva de 30 dias, concentrado | 0,5 | 3,9740% | 4,9780% |
| Maior média positiva de 30 dias, concentrado | 1,0 | 8,1055% | 10,2031% |

Os períodos começam em caixa e terminam à meia-noite UTC, sem receber funding terminal. O primeiro período tem 104 decisões semanais; o segundo, 143. Todos os cenários tiveram alocação em cada decisão, sem que isso indique capacidade de execução real. O caso concentrado é apenas um diagnóstico previamente fixado; seu maior resultado não o promove a estratégia selecionada.

A coorte mantém os vinte ativos definidos pela liquidez de janeiro de 2021, inclusive EOS e MKR. Foram verificados 123.065 eventos de funding no cache completo e preparados 37.006 estados diários com os sessenta campos econômicos e técnicos. Os intervalos efetivamente encontrados nesta coorte são de oito horas; testes sintéticos também cobrem intervalos de uma hora. A decisão usa dados encerrados à meia-noite, pagamentos estritamente anteriores a esse horário e execução hipotética às segundas 01h UTC. A receita inclui funding negativo. Os encerramentos de EOS e MKR foram processados; nenhum dos seletores mantinha peso nesses ativos nos horários de liquidação, e não houve alocação posterior às restrições conhecidas.

As fontes locais verificadas incluem 4.182 registros diários e de funding, 1.283 horários e 54 snapshots REST já preservados. Nenhum arquivo de mercado foi baixado nesta rodada. Nenhuma chamada JEV ou ordem foi enviada, e a carteira paper permaneceu separada. A triagem computa o pacote completo de indicadores, mas a hipótese econômica fixada usa funding, liquidez e volatilidade; não transforma indicadores adicionais em votos sem demonstrar contribuição preditiva.

A Binance calcula o pagamento de funding pela quantidade, mark price e taxa. Na operação spot/perp com quantidades iguais, o resultado também depende da mudança da diferença entre os preços das duas pernas e de seus custos. As regras de Portfolio Margin incluem descontos de garantia e os saldos negativos podem gerar juros. Esses efeitos precisam entrar em um backtest executável; o índice atual os omite. Fontes oficiais: [cálculo de funding](https://www.binance.com/en/support/faq/detail/360033525031), [garantias de Portfolio Margin](https://www.binance.com/en/support/faq/detail/937b8e81d03f475c8d7a0d42ec381510) e [saldos negativos](https://www.binance.com/en/support/faq/detail/c1df531bb7c44ea2a10919a74fd84f5e). As páginas atuais não comprovam regras idênticas em toda a série histórica.

O pequeno drawdown do índice de recebimentos, disponível no JSON com prefixo `funding_index`, não mede o drawdown da carteira. A proporção 1,0 também não reserva dinheiro separado para margem. O índice não é um limite superior matemático de toda estratégia spot/perp, pois variações favoráveis da diferença de preços podem acrescentar retorno. Os períodos históricos já foram examinados em outras pesquisas, portanto não constituem validação prospectiva.

Com receita idealizada entre 4,32% e 4,98% ao ano na proporção 0,5, a aquisição imediata de até 544 arquivos spot adicionais para estes mesmos seletores não é prioridade na busca de 50%. Não serão ampliadas alavancagem ou janelas apenas para aproximar o número solicitado. A conclusão é limitada a esta fonte de receita, regras, coorte e períodos; a meta permanece não atingida e nenhuma estratégia foi liberada para operar.

Validação: 246 testes passaram, incluindo 26 testes novos de causalidade, cobertura, alocação, composição, funding negativo, colisões, restrições contratuais e exclusão terminal. A revisão independente do código não encontrou bloqueios na triagem. Os arquivos escritos foram verificados como UTF-8 válido. Para reproduzir offline com o cache preservado: `uv run python -m jev_trader.funding_capacity_research`.

A auditoria independente dos resultados verificou os hashes dos artefatos e das 5.519 referências de fontes, reconstruiu o hash dos 123.065 eventos diretamente dos arquivos ZIP e snapshots REST, examinou 1.482 decisões semanais e 20.604 linhas de ranking e reconciliou contribuições positivas e negativas com o índice terminal nos doze cenários. Os hashes dos estados calculados coincidem entre entradas, relatório completo e resumo; os indicadores não foram recalculados de forma independente nessa auditoria. Nenhum bloqueio foi encontrado.

Hashes dos artefatos completos:

- Entradas: `ce72842e14144b0bb1827f554c964428da233ed7cbc9a26ec37f55efb2a25f12`.
- Relatório completo: `a31f7b02cd71b01ff8562d2003c7823b1e7880bdc9c95c051beae576013d8863`.
- Estados diários: `6858c7cf9f86d184fc292095082f5d11c9dfd96b7128eae0d374e53f8ab326e8`.
- Eventos de funding: `5168a275b90e6d4e9d2d98aa107dcfbd720bb55bea319ea688bf0186106f757f`.
