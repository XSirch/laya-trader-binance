# Ciclo 02 — alinhamento dos gates à Rev02

Registrado em 28/09/2026 após comparar a orientação vigente com os gates executáveis. Os gates para pesquisas futuras são:

- Cenário-base: EV líquido médio estritamente acima de 1,2% por operação, payoff ≥1, profit factor ≥1,25, pelo menos 200 operações completas e pelo menos oito semanas ativas.
- Cenário estressado: PnL líquido agregado positivo depois de dobrar taxa e slippage, preservando funding observado em USD-M.
- Acerto próximo de 70% é preferência, sem piso. Drawdown é reportado e minimizado entre candidatas qualificadas, sem teto de aprovação.

## Divergência corrigida

Antes deste alinhamento, os gates executáveis também exigiam EV médio positivo e payoff ≥1 no stress; o motor compartilhado ainda podia impor retorno médio em R, limite de drawdown e limite inferior de confiança configurável. A Rev02 não inclui essas condições como gates. Agora:

- `promotion_gate` aplica EV, payoff, profit factor, amostra e semanas ao cenário-base e exige somente PnL agregado positivo no stress.
- `mean_net_r`, EV/payoff/profit factor e quantidade de operações do stress ficam como diagnósticos, sem gates separados.
- O campo legado `max_drawdown` não bloqueia promoção. `confidence_lower_bound_required` também não transforma a preferência de acerto em requisito.
- Profit factor indisponível no cenário-base reprova como não avaliado; não é tratado como aprovação.

O script do Ciclo 02 usa a mesma regra de stress. Testes determinísticos cobrem stress positivo com EV/payoff de stress abaixo de zero, drawdown acima do valor legado configurado e win rate abaixo da preferência.

## Efeito sobre resultados já registrados

Os protocolos da reexecução corrigida, da sensibilidade e do filtro custo/stop permanecem imutáveis como registro do que foi pré-registrado e executado. Eles usavam a regra mais rígida. Seus relatórios não foram reescritos nem reexecutados: nenhum comparador da reexecução corrigida satisfez simultaneamente os gates-base; 16 combinações da sensibilidade tiveram amostra suficiente, mas EV-base negativo; e o filtro custo/stop teve no máximo 61 operações por variante. Portanto, remover os gates adicionais do stress não cria candidata e a decisão continua `target_not_demonstrated`.

Esta alteração não é um novo holdout, não valida rentabilidade e não autoriza paper ou ordens reais. Todo novo replay precisa registrar os gates Rev02 antes da avaliação.
