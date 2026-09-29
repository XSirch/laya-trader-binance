# Ciclo 11 — extensão cronológica de `rank_blend`

## Pergunta

O resultado histórico positivo de `rank_blend` persistiu na extensão disponível de 1º de agosto a 26 de setembro de 2026, após taxas e funding? A extensão serve para decidir se vale continuar a observar essa regra, não para aprovar uma estratégia.

## Motivo para preservar esta hipótese

A reanálise já existente de regras de futuros Binance USD-M encontrou para `rank_blend`, a 0,15% de custo por lado:

- H2/2025: 44 episódios, 63,64% de acerto, payoff 1,222 e EV +5,344% por episódio.
- Jan–jul/2026: 58 episódios, 60,34% de acerto, payoff 1,017 e EV +1,992%.
- Jan/2024–jul/2026: 252 episódios, 58,33% de acerto, payoff 1,031 e EV +2,850%; drawdown da carteira 10,787%.

A meta de 70% de acerto é uma preferência, e não será usada como gate rígido. O payoff agregado passa por margem estreita. O drawdown será informado e minimizado em comparações futuras, mas não há teto de aprovação. A pesquisa anterior examinou uma reamostragem em blocos que deixou incerteza material sobre EV e payoff; consultar o relatório-fonte antes de interpretar este ciclo.

## Hipótese e regra congeladas

- Instrumento: contratos perpétuos Binance USD-M; sem spot, ações, ETFs ou ordens reais.
- Sinal existente: `rank_blend`, média dos rankings de momentum de 30 dias, carry de 30 dias, baixa volatilidade de 30 dias e fluxo taker de 20 dias.
- Seleção: universo e elegibilidade idênticos ao código existente; long nos 20% de maior pontuação e short nos 20% de menor pontuação; exposição bruta de 50% e líquida inicial zero.
- Rebalanceamento: semanal, segunda-feira às 00:00 UTC na série diária; sinais usam apenas candles concluídos.
- Saída: rebalanceamento semanal seguinte, mudança de lado ou encerramento da avaliação.
- Componentes congelados: sinais, features, pesos, universo, frequência, sizing e lógica de saída. Nenhuma otimização de parâmetros ou filtro ML neste ciclo.

## Janela e custos

- Janela: 2026-08-01 00:00 UTC até 2026-09-26 00:00 UTC, inclusive como instante terminal de liquidação. Os candles diários de 1º a 25 de setembro são agregados dos snapshots horários Binance já arquivados; o candle horário que inicia o instante terminal fornece apenas o preço de encerramento e não entra nos sinais.
- Custos por lado: 0,10% comparável/base; 0,15% para comparação com a reanálise anterior; 0,20% como custo dobrado em relação ao base; e 0,30% como estresse severo. O funding continua incluído pelo método adverso de extremos horários já usado no projeto.
- Não abrir novamente a janela para selecionar limiares. Registrar todos os resultados, inclusive perdas e operações encerradas por proxy adverso de listagem.

## Medidas e decisão

Reportar operações completas e únicas, acerto líquido, payoff, EV líquido por operação sobre nocional bruto inicial, profit factor, semanas ativas, drawdown e retorno líquido da carteira para cada custo. Conferir a reconciliação da carteira com o avaliador diário já existente.

Para uma decisão econômica posterior, usar EV >1,2%, payoff ≥1, profit factor ≥1,25 e PnL positivo com custo dobrado; a taxa de acerto próxima de 70% é preferência. A consistência exige amostra suficiente e janelas futuras não sobrepostas. Esta janela de oito semanas, já vista em uma análise de outra regra, não é holdout independente e não pode concluir consistência, mesmo se positiva. Resultado negativo encerra `rank_blend` como candidato ativo; resultado positivo apenas mantém a hipótese para observação prospectiva congelada.

## Proveniência e limites

Os snapshots são respostas públicas REST Binance armazenadas localmente com hashes de conteúdo. A janela de agosto/setembro já foi examinada para outra combinação, e `rank_blend` foi selecionado para esta extensão depois de conhecidos os resultados históricos até julho; isso torna o ciclo exploratório. A série usa agregação diária e custos simulados, não fills executáveis. O resultado não autoriza ordens reais.
