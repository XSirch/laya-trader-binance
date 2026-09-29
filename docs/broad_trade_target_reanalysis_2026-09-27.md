# Reanálise por operação das regras amplas de futuros

## Resultado

Reagrupei as 24 regras já existentes do universo Binance USDT perpétuo; não mudei filtros, sinais, rebalanceamento ou parâmetros. A tabela usa custo de estresse de 0,15% por lado. Cada célula mostra episódios, acerto, payoff, EV líquido por episódio e drawdown da carteira.

O payoff é ganho médio líquido dividido pela perda média absoluta. O EV é PnL líquido médio como percentual do notional bruto inicial do episódio. Para a triagem, usei acerto ≥70%, payoff ≥1:1, EV >1,2%, drawdown ≤10%, ao menos 30 episódios e nenhuma saída proxy não resolvida; a regra também precisa manter esses gates nas duas janelas e drawdown combinado ≤10%.

| Regra já testada | Validação H2/2025 | Confirmação jan–jul/2026 | Combinado jan/2024–ago/2026 |
|---|---|---|---|
| `carry30` | n=37; 51,4%; payoff 1,34; EV +3,10%; DD 5,23% | n=43; 51,2%; payoff 1,25; EV +1,62%; DD 7,00% | n=202; 55,0%; payoff 1,03; EV +1,79%; DD 14,90% |
| `carry30_betahedged` | n=40; 52,5%; payoff 0,93; EV +0,27%; DD 5,76% | n=48; 52,1%; payoff 1,00; EV +0,44%; DD 6,92% | n=215; 54,4%; payoff 1,08; EV +2,15%; DD 12,33% |
| `low_volatility30` | n=30; 66,7%; payoff 1,43; EV +7,17%; DD 5,50% | n=40; 60,0%; payoff 1,49; EV +3,89%; DD 3,01% | n=173; 55,5%; payoff 1,11; EV +2,76%; DD 20,43% |
| `low_volatility30_betahedged` | n=30; 70,0%; payoff 1,25; EV +7,44%; DD 5,03% | n=38; 60,5%; payoff 1,63; EV +4,45%; DD 3,19% | n=166; 57,2%; payoff 1,03; EV +2,75%; DD 16,74% |
| `momentum30` | n=67; 44,8%; payoff 1,01; EV -1,24%; DD 8,66% | n=77; 41,6%; payoff 0,93; EV -2,38%; DD 17,90% | n=365; 46,0%; payoff 1,11; EV -0,36%; DD 31,31% |
| `momentum30_betahedged` | n=73; 45,2%; payoff 0,60; EV -5,36%; DD 7,39% | n=83; 44,6%; payoff 0,86; EV -2,27%; DD 17,67% | n=381; 45,9%; payoff 1,36; EV +1,22%; DD 29,81% |
| `momentum7` | n=122; 51,6%; payoff 1,24; EV +1,12%; DD 6,40% | n=139; 42,4%; payoff 1,17; EV -0,55%; DD 9,39% | n=708; 46,2%; payoff 1,21; EV +0,18%; DD 19,13% |
| `momentum7_betahedged` | n=132; 52,3%; payoff 1,20; EV +1,08%; DD 5,25% | n=151; 43,0%; payoff 1,38; EV +0,17%; DD 8,72% | n=749; 46,6%; payoff 1,20; EV +0,24%; DD 17,89% |
| `momentum90` | n=44; 40,9%; payoff 1,01; EV -2,98%; DD 20,96% | n=47; 48,9%; payoff 1,25; EV +1,08%; DD 6,18% | n=208; 43,3%; payoff 1,27; EV -0,30%; DD 28,17% |
| `momentum90_betahedged` | n=49; 38,8%; payoff 0,84; EV -5,53%; DD 19,19% | n=45; 48,9%; payoff 1,09; EV +0,29%; DD 6,10% | n=211; 44,5%; payoff 1,05; EV -1,55%; DD 25,78% |
| `momentum90_skip7` | n=41; 43,9%; payoff 0,87; EV -3,06%; DD 17,52% | n=47; 42,6%; payoff 2,02; EV +2,13%; DD 6,51% | n=218; 46,8%; payoff 1,11; EV -0,16%; DD 28,48% |
| `momentum90_skip7_betahedged` | n=44; 40,9%; payoff 0,29; EV -23,40%; DD 17,19% | n=45; 42,2%; payoff 1,69; EV +1,21%; DD 5,57% | n=228; 47,4%; payoff 0,66; EV -5,32%; DD 27,97% |
| `quality_momentum` | n=60; 55,0%; payoff 1,49; EV +3,76%; DD 4,50% | n=54; 53,7%; payoff 0,91; EV +0,28%; DD 6,79% | n=298; 49,0%; payoff 1,14; EV +0,63%; DD 17,51% |
| `quality_momentum_betahedged` | n=58; 55,2%; payoff 1,50; EV +3,92%; DD 3,17% | n=52; 55,8%; payoff 0,79; EV +0,01%; DD 7,61% | n=288; 50,0%; payoff 1,09; EV +0,59%; DD 12,19% |
| `rank_blend` | n=44; 63,6%; payoff 1,22; EV +5,34%; DD 4,44% | n=58; 60,3%; payoff 1,02; EV +1,99%; DD 4,52% | n=252; 58,3%; payoff 1,03; EV +2,85%; DD 10,79% |
| `rank_blend_betahedged` | n=41; 65,9%; payoff 1,03; EV +5,16%; DD 2,78% | n=57; 57,9%; payoff 0,96; EV +1,38%; DD 4,02% | n=242; 59,1%; payoff 0,97; EV +2,67%; DD 8,81% |
| `reversal1` | n=877; 48,6%; payoff 0,82; EV -0,43%; DD 28,11% | n=972; 47,9%; payoff 0,88; EV -0,29%; DD 24,64% | n=4886; 49,3%; payoff 0,85; EV -0,32%; DD 71,70% |
| `reversal1_betahedged` | n=905; 47,7%; payoff 0,79; EV -0,59%; DD 23,00% | n=1046; 46,7%; payoff 1,14; EV -0,01%; DD 22,66% | n=5121; 48,8%; payoff 0,87; EV -0,36%; DD 69,40% |
| `reversal7` | n=122; 45,9%; payoff 0,75; EV -1,80%; DD 18,24% | n=139; 56,1%; payoff 0,77; EV -0,06%; DD 7,21% | n=708; 50,6%; payoff 0,82; EV -0,83%; DD 41,43% |
| `reversal7_betahedged` | n=132; 47,0%; payoff 0,71; EV -1,81%; DD 15,16% | n=151; 55,0%; payoff 0,65; EV -0,93%; DD 4,95% | n=749; 50,6%; payoff 0,80; EV -0,94%; DD 38,30% |
| `taker_flow20` | n=56; 51,8%; payoff 1,43; EV +2,58%; DD 3,80% | n=56; 55,4%; payoff 0,74; EV -0,46%; DD 8,71% | n=293; 49,1%; payoff 1,25; EV +1,41%; DD 9,82% |
| `taker_flow20_betahedged` | n=58; 51,7%; payoff 1,42; EV +2,59%; DD 3,30% | n=53; 56,6%; payoff 0,60; EV -1,42%; DD 9,05% | n=286; 50,3%; payoff 1,26; EV +1,98%; DD 9,05% |
| `time_series_ensemble` | n=71; 32,4%; payoff 2,56; EV +3,16%; DD 11,77% | n=50; 52,0%; payoff 2,40; EV +12,57%; DD 9,46% | n=293; 33,1%; payoff 2,62; EV +4,37%; DD 24,14% |
| `time_series_ensemble_betahedged` | n=70; 41,4%; payoff 1,65; EV +2,27%; DD 4,91% | n=48; 47,9%; payoff 2,99; EV +14,35%; DD 3,24% | n=293; 36,9%; payoff 2,59; EV +6,78%; DD 7,92% |

## Decisão

Nenhuma regra aprovada nos gates completos.
Mesmo um resultado aprovado nesta tabela continua retrospectivo: todas as janelas foram examinadas no programa anterior e a confirmação não é prospectiva. Uma candidata só deve ser promovida depois de dados futuros com sinais e custos congelados.

## Método e proveniência

- Um episódio começa ao sair de caixa para long/short e termina ao voltar a caixa ou inverter o sinal; reequilíbrios semanais na mesma direção ficam no mesmo episódio.
- O reprocessamento reproduziu retorno, drawdown, taxas e funding do avaliador original para todas as regras, períodos e custos, com tolerância de `1e-8`; PnL líquido dos episódios fecha com o retorno total da carteira.
- O modelo cobra taxas no giro de cada rebalanceamento, usa os mesmos pagamentos de funding e proxies adversos do relatório original, e sinaliza saídas não resolvidas.
- Relatório original: SHA-256 `9fa70e1fd1b486072392333decde61f110019c1d39276c517ab749d97582d3a0`; manifesto de dados `11f72aa37a646cf46e7904337aced83e2aa06c052377f07c7596e0287465a05a`.
- Reanalisador: SHA-256 `583575e3c129c8a109e6487ac19f29056f0ffb884fd61e2d4dd4e72766d01181`.
- Ledgers por episódio: [CSV](../results/broad_trade_ledger_20260927.csv); métricas completas: [JSON](../results/broad_trade_target_reanalysis_20260927.json).

Nenhuma ordem real foi enviada.
