# Próxima família: interações não lineares

Protocolo registrado após observar a falha das regressões lineares de 10 e 60 entradas. Todos os períodos já utilizados continuam retrospectivos.

A próxima comparação usará os mesmos 60 campos, elegibilidade e percentis causais. Sobre os vetores de percentis, aplicar uma aproximação fixa de kernel gaussiano por 64 características aleatórias de Fourier, semente 548. Comparar comprimentos de escala 1, 2 e 4, mantendo penalidade ridge 0,1. As características serão `sqrt(2/64) * cos(w dot x + b)`, com componentes de `w` normais de desvio padrão igual ao inverso da escala e fases uniformes entre zero e 2π. Os pesos aleatórios não serão treinados nem escolhidos após o resultado.

O objetivo é testar interações entre indicadores sem acrescentar informação futura ou selecionar apenas os sinais que deram lucro. Comparar os três modelos nas duas formas de dimensionamento já existentes, totalizando seis variantes, além da referência em caixa. Permanecem janela de treino de 104 semanas, mínimo de 52 semanas completas, purga temporal, exposição bruta de 50%, hedge estimado de beta e custos de 0,10%/0,15%/0,30% por lado.

Usar 2022–2023 apenas para seleção. Reportar 2024, 2025 e 2026, inclusive as perdas. Preservar separadamente execução estrita e diagnóstico condicionado às faixas de liquidação. Uma posição sem preço e sem faixa documentada deve interromper a simulação. Nenhuma hipótese será considerada comprovada somente porque uma variante ficou positiva no agregado.

O próximo relatório deve comparar erros com a previsão nula, concentração por ativo e regularidade temporal. A correção estatística da nova família não elimina a seleção acumulada das rodadas anteriores; essa limitação deve permanecer visível.

Este arquivo é um protocolo para implementação e avaliação futuras, não um resultado executado. Não há autorização de ordens reais.
