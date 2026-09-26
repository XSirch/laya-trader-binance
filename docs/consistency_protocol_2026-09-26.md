# Expectativa, dispersão de resultados e períodos de perda

Reavaliar a combinação fixa de baixa volatilidade e carry protegido, com e sem trailing de carteira de 4%, sem selecionar novo vencedor ou alterar posições. Uma janela negativa isolada não implica ausência de expectativa positiva. Também não basta observar retorno acumulado positivo para demonstrar consistência, principalmente após múltiplas buscas no histórico.

Usar a curva contínua dos replays anteriores a custos por lado de 0,15% e 0,30%. Separar os retornos diários terminados até 1/agosto/2026 dos posteriores. Calibrar cenários somente no primeiro trecho; avaliar a perda do trecho de agosto–setembro como continuação da mesma carteira, sem reinicializar posições. Essa é uma separação cronológica para diagnóstico, não uma alegação de seleção prospectiva: ambos os trechos já foram inspecionados.

Reportar retorno anualizado, queda máxima observada nas amostras diárias, duração sem recuperar o pico e janelas móveis de 30, 90, 180 e 365 dias. Janelas sobrepostas são descrições dependentes; não contar cada uma como observação independente. Preservar também a queda máxima horária original, que pode ser maior que a diária.

Gerar 5.000 cenários por variante/custo usando blocos circulares de 14, 30 e 60 dias, semente 1907. Cada cenário tem o comprimento exato do trecho recente. Reportar percentis 5/50/95 do retorno e da queda máxima diária, frequência de perda e frequência de resultado tão ruim quanto o observado. Essas frequências são condicionais à hipótese de que o histórico anterior represente o futuro; não são probabilidades calibradas de rentabilidade nem testes que validam a estratégia. Não ajustar os blocos pelo resultado obtido.

Reportar também o intervalo individual de crescimento anualizado obtido por bootstrap do trecho anterior a agosto, com blocos de 30 dias e 5.000 amostras. Ele não corrige a escolha da estratégia após pesquisas anteriores e não deve ser usado sozinho como critério de aprovação.

O objetivo permanece uma estratégia com expectativa líquida positiva e risco sustentável. Esta análise melhora a interpretação dos resultados, mas não resolve viés de seleção, mudanças de regime, liquidez, execução real ou ausência de acompanhamento prospectivo. Não reclassificar a estratégia como pronta com base apenas em a perda estar dentro de um intervalo histórico amplo.
