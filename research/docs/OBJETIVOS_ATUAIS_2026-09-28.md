# Critérios atuais da pesquisa de estratégia

Atualização registrada em 28/09/2026. Este documento prevalece sobre metas antigas
de retorno anual/mensal e sobre os limiares anteriores de drawdown e taxa de acerto.
Os handoffs anteriores continuam como histórico da arquitetura e dos experimentos.

## Escopo

- Pesquisar somente pares cripto Spot e futuros perpétuos USD-M da Binance.
- Fazer entradas e saídas com regras causais; não operar também é uma decisão válida.
- Não habilitar ordens reais como consequência de resultados de pesquisa ou paper.

## Critérios econômicos

- **Expectativa líquida por operação:** acima de 1,2% do nocional inicial da operação,
  após taxas, slippage e, em USD-M, funding.
- **Payoff:** ganho líquido médio dividido pela perda líquida média absoluta de pelo
  menos 1:1. A faixa preferida é 1,2:1 a 1,5:1.
- **Taxa de acerto:** buscar aproximadamente 70%, como preferência, não como gate
  rígido. Uma taxa um pouco menor pode ser aceitável quando o lucro líquido for
  consistente e os critérios econômicos forem atendidos.
- **Drawdown:** não existe teto numérico de aprovação. Medir e reportar o drawdown
  máximo e buscar reduzi-lo entre candidatos que preservem lucro e payoff; drawdown
  menor por si só não torna uma estratégia sem lucro preferível.

Mostrar sempre o resultado por operação sobre seu nocional inicial e o retorno da
carteira sobre o patrimônio destinado ao sistema. Não usar um como substituto do outro.

## Evidência de consistência

Uma triagem curta pode descartar hipóteses rapidamente, mas não confirma consistência.
Se uma hipótese sobreviver, ampliar a avaliação com janelas temporais não sobrepostas,
custos-base e estressados, número de operações e resultados por janela/ativo/direção.
Destacar concentração do lucro em poucas operações ou períodos. Não ajustar repetidamente
no mesmo período de avaliação até obter aprovação; registrar resultados negativos.

## Diferenças conhecidas no pacote atual

O código e as configurações agora refletem EV líquido mínimo de 1,2% por nocional,
payoff mínimo de 1:1, taxa de acerto como preferência e ausência de teto de drawdown.
Entre candidatos aprovados, o seletor prefere menor drawdown. Permanecem gates adicionais
de evidência: pelo menos 200 operações, oito semanas ativas, profit factor de 1,25 e
resultado positivo sob custos estressados. Esses gates evitam aprovar amostras curtas,
mesmo quando os objetivos econômicos aparentam passar.

O piso inicial de probabilidade foi reduzido a 35% para permitir procurar resultados
rentáveis abaixo da preferência de 70%; a busca também testa probabilidades maiores.
Em 28/09/2026, nenhum fold Spot ou USD-M passou pelos critérios econômicos e de evidência.
Consulte `RESULTADOS_TREINAMENTO_GPU_2026-09-28.md`; o pacote continua em pesquisa e não
autoriza ordens reais.
