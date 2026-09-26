# Pesquisa com universo histórico de 20 contratos

Ainda não foi comprovada uma estratégia lucrativa e consistente. Esta rodada amplia a pesquisa para 20 contratos selecionados pelo volume financeiro de janeiro de 2021, preserva contratos posteriormente retirados e compara 24 hipóteses. Os arquivos de evidência acompanham este relatório; os resultados completos com curvas e decisões ficam em `results/`.

## Dados e seleção

Foram verificados 4.024 arquivos mensais de candles diários, marcação e funding, mais 158 suplementos diários. A verificação usa os checksums publicados pela Binance. Lacunas internas dos arquivos mensais foram reparadas com arquivos diários oficiais antes de recalcular os resultados. Os candles sem negócios emitidos depois do encerramento de MKR não foram tratados como preços negociáveis.

A seleção de parâmetros usa 2022–2023. A avaliação inclui 2024, os dois semestres de 2025 e janeiro–julho de 2026. Esses períodos posteriores já foram examinados em outras rodadas; não constituem uma amostra intocada. A melhor regra selecionada no desenvolvimento, baixa volatilidade, perdeu em 2024. Nenhuma das 24 regras passou todos os critérios posteriores.

A combinação de baixa volatilidade com carry e hedge de beta foi criada **depois de examinar o screening**. Seus componentes foram escolhidos mecanicamente pelo desenvolvimento, mas isso não elimina o viés da pesquisa. Ela não foi pré-registrada como hipótese independente.

## Candidato fixado e execução horária

O arquivo `broad_candidate_freeze_2026-09-26.json` fixa a combinação, as fontes e os hashes antes da avaliação horária e de agosto. São pesos iguais entre baixa volatilidade e carry com hedge de beta, exposição bruta alvo de até 50%, rebalanceamento às segundas-feiras às 01:00 UTC e sinais calculados até 00:00 UTC. A decisão é inteiramente do script.

Foram adquiridos 1.265 arquivos horários. O replay usa uma carteira global, contabiliza variações de preços, custos sobre mudanças de quantidade e funding com limites adversos dos preços de marcação horários. Uma posição com preço ausente interrompe o replay; não há encerramento inventado. Colisões de funding e entrada não geram crédito automático para posições recém-abertas. A liquidação terminal exclui funding posterior ao intervalo de posse.

Resultados de janeiro de 2024 a julho de 2026:

| Execução e custo por lado | Retorno acumulado | Queda máxima horária | Meses positivos |
| --- | ---: | ---: | ---: |
| 01:00 UTC; 0,10% | 37,50% | 12,43% | 20/31 |
| **01:00 UTC; 0,15% — configuração principal** | **35,50%** | **12,49%** | **20/31** |
| 01:00 UTC; 0,30% | 29,65% | 12,70% | 19/31 |
| 02:00 UTC; 0,15% — sensibilidade | 38,71% | 10,81% | 21/31 |

A sensibilidade das 02:00 não substitui a configuração principal após observar o resultado. A curva principal ainda falha no critério de pelo menos dois terços dos meses positivos. No screening diário, o intervalo estatístico de retorno da combinação inclui zero e a correção de comparações não rejeita a hipótese nula. O intervalo não deve ser atribuído automaticamente ao novo replay horário.

## Extensão cronológica de agosto

A configuração principal foi avaliada sem reajuste entre 1º de agosto e 31 de agosto de 2026 às 23:00 UTC. O último horário foi usado porque o arquivo mensal não contém a abertura de 1º de setembro. A simulação começa em caixa, inclui as entradas e encerra as posições; não é a continuação contábil de uma carteira já aberta em julho.

| Custo por lado | Retorno | Queda máxima horária |
| --- | ---: | ---: |
| 0,10% | -2,39% | 4,34% |
| **0,15%** | **-2,46%** | **4,34%** |
| 0,30% | -2,66% | 4,37% |

O mês negativo é evidência contra declarar consistência a partir do retorno acumulado anterior. Agosto foi avaliado depois de fixar o candidato, mas continua sendo uma extensão histórica retrospectiva, não um teste prospectivo em produção.

## Limites e continuação

O replay não comprova execução de ordens reais, impacto de mercado para um capital específico, regras exatas de liquidação nem disponibilidade operacional. A queda máxima é medida nas observações horárias; um limite adverso intrahorário adicional está no JSON. As marcas exatas de cada pagamento de funding ainda não foram obtidas para todo o histórico.

Próximas verificações: concluir a extensão até setembro com snapshots públicos rastreáveis, analisar atribuição por ativo e estabilidade da exposição, e submeter novas hipóteses a seleção temporal sem alterar retroativamente os critérios desta rodada. Nenhuma operação real foi enviada. O JEV permanece opcional para pontuar critérios conjuntamente; não houve gasto adicional com sua API nesta rodada.

Reprodução: `python -m jev_trader.broad_research`, `python -m jev_trader.broad_combo`, `python scripts/snapshot_broad.py`, `python -m jev_trader.broad_execution`, `python scripts/broad_august_check.py`. A primeira geração do snapshot fixa a configuração; execuções posteriores preservam esse arquivo e os replays rejeitam alterações no código da estratégia fixada.
