# Próxima hipótese: previsão conjunta e risco relativo

Este protocolo é registrado depois de observar a extensão negativa da combinação fixa. Todo o histórico até 26 de setembro de 2026 está, portanto, contaminado pela pesquisa e será rotulado como retrospectivo.

A pergunta é se uma previsão conjunta dos fatores disponíveis consegue ordenar retornos relativos futuros melhor que os rankings fixos. Não serão escolhidos ativos a partir de seus resultados individuais recentes.

1. Preservar o universo formado pela liquidez de janeiro de 2021. Usar observações semanais de cada ativo com pelo menos 200 dias completos e funding disponível. Transformar as entradas em percentis da seção transversal observável naquela data: momentum 7/30/90, reversão 1/7, carry 30, volatilidade 30, fluxo agressor 20, beta 60 e ensemble temporal de médias. Os indicadores técnicos adicionais da rodada multifatorial anterior serão uma família separada, não acrescentados seletivamente depois do resultado.
2. O alvo é o retorno relativo da semana seguinte, medido entre aberturas negociáveis, incluindo funding. Descontar a média da seção transversal contemporânea do alvo. Treinar somente depois do encerramento de toda a janela do alvo; purgar a semana mais recente ainda incompleta.
3. Comparar regressão ridge com penalidades 0,1, 1 e 10, em janela móvel de 104 semanas, e uma previsão nula como referência. Exigir ao menos 52 semanas anteriores. Ponderar as semanas igualmente para que períodos com mais contratos não dominem o treino. Registrar o máximo timestamp de cada alvo usado.
4. Comparar duas formas de converter previsões em carteira: os extremos com pesos monetários iguais e os extremos com pesos inversos à volatilidade observada, acrescentando hedge BTC para neutralizar o beta estimado. Limitar a exposição bruta a 50% e manter os filtros históricos de liquidez. O script decide as posições; JEV só poderá pontuar aderência, caso uma hipótese separada justifique seu uso.
5. Selecionar configuração pelo desenvolvimento até dezembro/2023, avaliar todos os anos posteriores, custos de 0,10%, 0,15% e 0,30% por lado, atraso de execução e contribuições por ativo. Comparar erros de previsão com a previsão nula e preservar também as variantes que falharem.
6. Se houver resultado promissor, exigir replay horário, análise estatística com correção pelas variantes desta família e coleta prospectiva sem reajuste. Nenhum retorno retrospectivo isolado autoriza declarar a meta atingida.

Este arquivo especifica um experimento futuro; não afirma que os modelos já foram implementados ou aprovados.
