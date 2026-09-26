# Sensibilidade à indisponibilidade de um ativo

Manter a regra multifatorial e o trailing de carteira de 4% já fixados. Remover, separadamente, cada um dos vinte ativos do universo e recalcular os rankings e pesos pelas mesmas regras. Comparar com a carteira completa, com e sem trailing, com custo de 0,15% por lado e entrada semanal às 01:00 UTC. Avaliar o período contínuo de janeiro/2024 a 26/setembro/2026 e a janela independente de agosto–setembro/2026.

A remoção afeta o universo de negociação, não o histórico usado para calcular indicadores dos demais ativos. Retirar BTC também indisponibiliza sua função de proteção; a regra existente então deixa a metade de carry em caixa, sem substituí-la nem aumentar a outra metade. Esse caso mede uma dependência estrutural diferente e será identificado separadamente.

Se houver preço ausente de uma posição mantida, preservar a falha estrita e não inventar liquidação. Não selecionar a exclusão mais lucrativa como nova estratégia. A análise é retrospectiva e serve para medir dependência do universo; não representa confirmação fora da amostra.
