# A vantagem incremental do trailing é concentrada

A comparação pareada usa exatamente os mesmos dias e a mesma estratégia de sinais, com e sem trailing. A razão entre os patrimônios mede a contribuição incremental do controle de risco, em vez de atribuir ao stop todo o lucro da estratégia.

O trailing de carteira de 4% acrescentou 8,41 pontos percentuais ao retorno acumulado da referência. Isso equivale a patrimônio final 6,51% maior. Entretanto, dos 33 meses, somente cinco tiveram retorno proporcional superior à referência; oito tiveram retorno inferior e vinte foram equivalentes, com tolerância numérica de 1e-10 ponto percentual. A concentração é compatível com um mecanismo de proteção acionado esporadicamente, mas não comprova superioridade recorrente.

Zerar retrospectivamente as contribuições dos três melhores dias para o ganho relativo reduz esse ganho de +6,51% para -0,17%. Com cinco dias, cai para -2,40%. Este é um diagnóstico de concentração: não representa uma carteira executável nem permite ignorar esses dias na negociação.

O bootstrap pareado, com blocos circulares de 30 dias e 2.000 amostras, produziu intervalo de 95% para o crescimento relativo anualizado de -2,15% a +8,31%. O p-valor ajustado às nove variantes de trailing foi 0,605. Blocos de 14, 60 e 90 dias também produziram intervalos que incluem zero. O ajuste cobre apenas essa família, não todo o histórico de pesquisa; não há confirmação prospectiva.

Na atribuição contábil da diferença de retorno, DOGE contribuiu +4,16 pontos percentuais, XLM +2,87 e SUSHI +2,71. Outras contribuições compensaram parte disso. Esses números incluem alterações de exposição e capitalização; excluir um ativo exige outro replay e não pode ser inferido por simples subtração.

Conclusão operacional: manter o trailing como candidato a redução de risco, sem tratá-lo como fonte comprovada de lucro adicional. A redução de queda máxima observada no histórico permanece válida, mas a hipótese de aumento consistente do retorno não recebeu suporte suficiente. Não recalibrar a distância usando esses mesmos resultados. Nenhuma ordem real ou chamada adicional ao JEV foi feita.

Evidência: `trailing_increment_2026-09-26.json`. Reprodução: `python scripts/analyze_trailing_increment.py`, com `results/trailing_research.json` disponível. O artefato registra os hashes do relatório de origem e do script de análise.
