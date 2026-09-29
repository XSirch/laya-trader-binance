# Protocolo: hipótese short-only para a regra de baixa volatilidade

## Motivação e viés de seleção

A decomposição por direção do filtro de retorno HGB mostrou resultado melhor nas pernas short do que nas long em H2/2025 e jan-jul/2026. Esta hipótese surge após observar esses números; toda métrica histórica abaixo é geração de hipótese, sujeita a viés de seleção, e exigirá período prospectivo congelado antes de qualquer alegação de consistência.

## Regra fixa

Manter o candidato `low_volatility30_betahedged`, suas features e o mesmo HGB regressor walk-forward do protocolo de EV. Treinar apenas com operações de referência já encerradas estritamente antes da decisão, janela móvel de 104 semanas, mínimo de 100 episódios completos e features originais mais direção. Aceitar uma perna short quando o modelo prever retorno líquido `>=1,2%` do notional, com o mesmo rótulo calculado a 0,15% de custo por lado. Não abrir pernas longas. Uma short já mantida na mesma direção continua aberta conforme a regra anterior.

Alocar 25% do patrimônio de notional bruto ao conjunto de shorts, distribuído igualmente entre pernas aceitas; sem alavancagem e sem comprar pernas para neutralizar beta. Usar funding, preços, custos, calendário, rebalanceamento, fills e saídas do mesmo motor do estudo anterior. Comparar custos de 0,10% e 0,15% por lado. Não alterar o limiar, modelo, features ou datas após observar resultados.

## Avaliação

Reportar acerto, payoff líquido, EV por episódio sobre notional, quantidade, retorno e drawdown marcado pelo motor existente. Gate exploratório em validação H2/2025 e confirmação histórica jan-jul/2026: ao menos 30 operações em cada janela, acerto `>=70%`, payoff `>=1`, EV `>1,2%` e drawdown `<=10%` no estresse; combinado também deve manter drawdown `<=10%`. O ledger-fonte não contém um limite adverso intrabar para esta regra. Mesmo aprovação nessas datas não seria confirmação independente: o sinal direcional foi escolhido ao inspecionar as mesmas janelas.

Sem downloads, chamadas JEV, mudanças no paper observer ou ordens reais.
