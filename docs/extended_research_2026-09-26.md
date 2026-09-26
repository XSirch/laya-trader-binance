# Segunda rodada: previsões e regras diárias

Data: 26/09/2026. **Nenhuma estratégia demonstrou consistência suficiente para operação real.** O RSI2 diário foi a hipótese escolhida pela calibração e merece acompanhamento simulado; o histórico ainda não comprova uma vantagem persistente.

Esta é a rodada estatística inicial. A solicitação posterior de combinar os indicadores em uma única chamada ao JEV, mantendo a decisão no script, está documentada na [rodada multifatorial](multifactor_research_2026-09-26.md). O RSI2 não limita o escopo dessa rodada posterior.

## Escopo e rastreabilidade

O repositório atual é `jev-binance-research`, substituindo o antigo treinamento Laya. Foram reutilizados os 176 arquivos horários oficiais de BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, conferindo os hashes durante a leitura. O conjunto tem SHA256 `367de91c7b912d18eb01cef7fc8bc9a3597018ee2b00ca9ce5bcc7bbef291912`.

Os candles diários foram agregados por UTC desde abril de 2023, exigindo exatamente 24 horas por dia. Assim, a lacuna conhecida de março de 2023 não entra nos indicadores diários. O período de desenvolvimento é 2024; a calibração é janeiro–junho de 2025; os períodos posteriores são julho–dezembro de 2025 e janeiro–julho de 2026. Agosto fornece aquecimento/observações adicionais ao gerador, mas os retornos reportados encerram em 01/08/2026. Nenhum dado posterior a uma decisão entra em seu treinamento.

A evidência integral está em [extended_research_2026-09-26.json](extended_research_2026-09-26.json), incluindo parâmetros, métricas mensais e por ativo, hashes do código e do cache JEV, auditoria de treinamento, seleção trimestral e testes de robustez. O JSON em `results/extended_research.json` é regenerável localmente.

## Métodos testados

Esta rodada comparou 19 alternativas: 11 regras técnicas diárias, cinco previsões estatísticas, comprar e manter, caixa e seleção trimestral. A comparação horária original, com oito alternativas, também foi recalculada após a correção dos custos.

- Tendências por médias 10/50, 20/100 e 50/200 dias; rompimentos 20/10 e 55/20; reversões RSI2 e RSI14; momentum de 30, 90 e 180 dias; combinação por maioria de três regras.
- Regressão linear com duas regularizações fixas, média dos 50 estados históricos mais próximos, média condicionada ao regime e média histórica. As cinco previsões estimam retorno de sete dias, usam até 730 dias anteriores, exemplos espaçados sete dias e treinamento conjunto dos quatro ativos. Variáveis: retornos de 1, 7 e 30 dias, distância da média de 60 dias e volatilidade de 14 dias, com escalas fixas.
- Decisão estatística no fechamento de domingo, execução na abertura de segunda e manutenção até a próxima decisão semanal. Compra somente quando a previsão supera 0,50%. Os rótulos de treino terminam até a abertura do próprio dia da decisão; 149 registros de auditoria confirmam essa ordem temporal.
- Seleção trimestral com aproximadamente 12 meses anteriores, encerrados na abertura do dia anterior ao trimestre. Se nenhuma regra passa pelos critérios existentes, permanece em caixa. A escolha e o capital evoluem cronologicamente.

Os parâmetros foram definidos antes da execução desta rodada. Todos os resultados posteriores são **exploratórios**, pois pesquisas anteriores já observaram este histórico. Comparar mais hipóteses não transforma esses meses em um teste final independente.

## Execução e critérios

As ordens simuladas usam a abertura seguinte ao candle completo. Cada ativo recebe 25% do capital inicial, sem rebalanceamento entre parcelas, alavancagem ou posições vendidas. O caixa rende zero. Cada janela isolada começa e termina sem posição; o resultado combinado mantém o capital ao longo de todo o período e, por isso, não é o produto simples dos resultados das janelas reiniciadas.

Custo-base: 0,15% por lado. Custo conservador: 0,25% por lado. São hipóteses, não taxas verificadas na conta. Foi corrigido o simulador para aplicar o custo de entrada ao capital **antes** do retorno de mercado. A primeira documentação permanece como registro histórico; os novos replays usam a correção.

Mantiveram-se os critérios anteriores: pelo menos 12 entradas por janela, retorno positivo nos dois custos, pelo menos dois terços dos meses positivos no custo-base e drawdown conservador de até 25%. Nenhuma alternativa passou nas três janelas. Permanecer em caixa durante quedas pode ser desejável, mas ausência de operações não comprova rentabilidade recorrente.

## Resultados

Retornos líquidos com custo de 0,25% por lado. Período combinado: janeiro/2025–julho/2026. Drawdown medido nas aberturas diárias nesta tabela.

| Alternativa | 2025 H1 | 2025 H2 | Jan–jul/2026 | Combinado | Drawdown combinado |
|---|---:|---:|---:|---:|---:|
| Tendência 10/50 | +6,15% | +21,81% | -19,53% | +8,41% | 28,43% |
| RSI2 diário | +3,03% | +3,27% | 0,00% | +5,76% | 8,75% |
| Momentum 30 dias | -10,22% | +22,42% | -2,23% | +7,66% | 13,28% |
| Seleção trimestral | 0,00% | +3,23% | 0,00% | +3,23% | 6,98% |
| Comprar e manter | -9,38% | +2,85% | -35,12% | -39,04% | 60,58% |
| Caixa | 0,00% | 0,00% | 0,00% | 0,00% | 0,00% |

O RSI2 foi selecionado exclusivamente pelos critérios e pelo retorno conservador da calibração, antes de usar as janelas posteriores para essa seleção. Teve 37 entradas no período combinado, sete meses positivos em 19 e nenhuma entrada em janeiro–julho de 2026. A seleção trimestral operou apenas no quarto trimestre de 2025, escolhendo RSI2, com 11 entradas; nos demais trimestres ficou em caixa.

As regressões tiveram -47,91% e -47,50%; os 50 vizinhos históricos, -21,72%; a média por regime, -11,96%; e a média histórica, -33,94%. Em 324 previsões avaliáveis, os cinco modelos tiveram erro absoluto médio entre 6,08 e 6,27 pontos percentuais, pior que os 5,90 pontos de prever retorno zero. A taxa de acerto direcional variou de 42,59% a 50,62%. Ativos correlacionados e rótulos semanais não constituem 324 observações independentes.

## Robustez do RSI2 selecionado

| Verificação | Resultado combinado |
|---|---:|
| Custo-base, 0,15% por lado | +7,73% |
| Custo conservador, 0,25% por lado | +5,76% |
| Custo dobrado, 0,50% por lado | +0,98% |
| Execução atrasada em um dia, custo conservador | +4,52% |
| Exclusão de um ativo por vez, custo conservador | +2,46% a +9,85% |

Reavaliar a carteira nas aberturas horárias mantém o retorno de +5,76% e eleva o drawdown observado a 9,23%. Isso ainda não mede as perdas intrahora nem garante execução nos preços usados. O intervalo descritivo de 95% por reamostragem de blocos de três meses para o retorno mensal geométrico vai de -0,46% a +1,11%. Ele inclui zero, usa somente 19 meses e não corrige a seleção entre múltiplas hipóteses.

## JEV: contribuição isolada

Foram reutilizadas somente respostas existentes do JEV 1.13 para a regra **horária** RSI14. Não houve novas chamadas pagas. O teste compara regra original, checklist numérico direto e o mesmo checklist acrescido da aprovação JEV.

| Janela | RSI14 original | Checklist direto | Checklist + JEV | Entradas direto/JEV |
|---|---:|---:|---:|---:|
| Calibração | -1,42% | +0,01% | +0,55% | 9/8 |
| Validação | -3,79% | -0,13% | -0,13% | 10/10 |
| Confirmação | -4,54% | -3,41% | -3,41% | 17/17 |

O JEV alterou uma decisão na calibração e nenhuma nas duas janelas posteriores. Portanto, este experimento não demonstrou benefício adicional posterior ao filtro numérico. Sua saída mede aderência a um checklist, não probabilidade de lucro. Não foi usado para selecionar retroativamente os parâmetros da nova pesquisa.

## Hipótese fixada para acompanhamento futuro

O candidato para observação simulada é o RSI2 diário: comprar quando RSI de Wilder de dois dias é menor ou igual a 10 e fechamento está acima da média simples de 200 dias; sair quando RSI2 chega a 60 ou o fechamento cai abaixo da média. Decidir após fechamento UTC, executar na próxima abertura e manter no máximo uma posição comprada por parcela. Preservar os quatro ativos e os parâmetros; não excluir um ativo por ter desempenho ruim depois.

Essa hipótese permanece **não aprovada para dinheiro real**. A avaliação prospectiva precisa começar após o congelamento desta versão, registrar spreads, preços executáveis e taxas reais, e manter os critérios de aprovação sem ajustes retrospectivos. Uma janela sem operações deve continuar marcada como evidência insuficiente. Não foi iniciada operação nem um serviço contínuo de monitoramento.

Limitações adicionais: universo escolhido retrospectivamente, possíveis vieses de sobrevivência, ausência de impostos, rendimento do caixa e custos específicos da conta. A estratégia com o maior retorno nesta tabela não foi automaticamente declarada vencedora.

## Reprodução e fontes

```powershell
uv sync --python 3.13
uv run python -m unittest discover -s tests -v
uv run jev-trader research-cached
uv run jev-trader research-extended
uv run python scripts/check_encoding.py
```

As fontes primárias consultadas foram a [documentação dos arquivos públicos da Binance](https://github.com/binance/binance-public-data/blob/master/README.md), incluindo checksums e unidades dos timestamps, e a [documentação conceitual do JEV na OpenRouter](https://openrouter.ai/blog/insights/what-is-jev/).
