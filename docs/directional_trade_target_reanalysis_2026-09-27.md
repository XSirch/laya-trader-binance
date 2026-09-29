# Reavaliação por operação: futuros direcionais já testados

## Resultado

Reagrupei os sinais diários já existentes em episódios de posição para medir acerto, payoff e EV contra as metas atuais. Não alterei sinais, parâmetros, universo nem janelas; 2024 continuou sendo o período original de seleção. O universo são contratos perpétuos Binance de BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, com posições long e short conforme cada regra.

A tabela mostra o custo de estresse de 0,15% por lado. Cada célula contém número de episódios, taxa de acerto, payoff, EV líquido por episódio e drawdown máximo da carteira. O EV é PnL líquido médio dividido pelo notional bruto inicial do episódio. Drawdown é calculado separadamente sobre a curva de patrimônio da carteira.

| Regra preexistente | Validação H2/2025 | Confirmação jan–jul/2026 |
|---|---|---|
| EMA 8/32 | n=20; 45,0%; payoff 3,52; EV +8,35%; DD 8,62% | n=38; 26,3%; payoff 2,00; EV -1,35%; DD 14,42% |
| EMA 16/64 | n=13; 61,5%; payoff 4,09; EV +15,23%; DD 7,37% | n=17; 41,2%; payoff 1,44; EV +0,05%; DD 12,08% |
| EMA 32/128 | n=9; 55,6%; payoff 3,76; EV +11,81%; DD 10,01% | n=4; 100,0%; payoff indefinido; EV +36,91%; DD 9,48% |
| SMA 20/100 | n=11; 72,7%; payoff 5,21; EV +18,63%; DD 6,99% | n=12; 50,0%; payoff 1,01; EV +0,06%; DD 14,52% |
| Canal 20/10 | n=22; 50,0%; payoff 1,28; EV +1,32%; DD 10,59% | n=27; 29,6%; payoff 2,25; EV -0,20%; DD 10,94% |
| Canal 55/20 | n=9; 55,6%; payoff 3,55; EV +10,18%; DD 5,38% | n=16; 37,5%; payoff 0,58; EV -4,48%; DD 11,80% |
| Momentum 30d | n=57; 31,6%; payoff 5,00; EV +2,63%; DD 5,54% | n=93; 30,1%; payoff 1,64; EV -0,79%; DD 11,55% |
| Ensemble de EMAs | n=13; 53,8%; payoff 6,22; EV +26,34%; DD 6,18% | n=17; 35,3%; payoff 4,12; EV +5,60%; DD 10,99% |
| Multifator direcional | n=32; 31,2%; payoff 2,84; EV +0,78%; DD 4,99% | n=16; 56,2%; payoff 4,24; EV +6,19%; DD 5,06% |
| Cross-section 30d | n=43; 51,2%; payoff 1,44; EV +0,98%; DD 2,79% | n=79; 44,3%; payoff 1,14; EV -0,19%; DD 3,63% |

## Interpretação

Nenhuma regra atingiu simultaneamente acerto próximo de 70%, payoff mínimo 1:1, EV acima de 1,2% por episódio e drawdown de até 10% tanto na validação quanto na confirmação. Nenhum período por regra chegou a 100 episódios; essas métricas são triagem histórica e não evidência de consistência futura.

A SMA 20/100 pareceu forte na validação (11 episódios: 72,7% de acerto, payoff 5,21 e EV +18,63%), mas na confirmação teve 12 episódios, acerto de 50%, EV +0,06% e drawdown de 14,36%. A reversão entre janelas rejeita essa hipótese. EMA 32/128 teve quatro episódios vencedores na confirmação, sem perdas observadas: o payoff é indefinido, e quatro observações não sustentam uma taxa de acerto de 100%.

As regras com drawdown abaixo de 10% nas duas janelas — como cross-section 30d e multifator direcional — ainda ficaram longe do acerto e do EV pedidos. Algumas regras de tendência apresentaram EV alto em uma janela, mas a taxa de acerto ficou baixa, o drawdown ultrapassou 10% ou a janela seguinte reverteu o resultado.

## Método e limites

- Um episódio começa quando a posição passa de flat para long/short e termina quando volta a flat ou inverte o sinal. Rebalanceamentos diários na mesma direção permanecem no mesmo episódio.
- Os sinais são calculados no fechamento diário anterior e executados às 01:00 UTC. O replay marca PnL por preços horários, cobra o giro da posição e inclui pagamentos de funding observados.
- A taxa de estresse de 0,15% por lado é aplicada ao notional negociado, inclusive rebalanceamentos. São custos assumidos; não equivalem a fills confirmados nem incluem todos os riscos de liquidação.
- Os quatro ativos compartilham sleeves separados; episódios de ativos diferentes podem se sobrepor. O EV por episódio não é retorno sobre margem nem previsão de EV da conta.
- A confirmação já foi examinada dentro do programa histórico anterior, portanto não é um holdout futuro intocado. Estratégias diárias também não testam a ideia de decisão a cada minuto.

## Proveniência

- Replay e métricas por episódio: [JSON da reanálise](../results/directional_trade_reanalysis_20260927.json).
- Ledger e implementação original: [directional.py](../src/jev_trader/directional.py); reporte original: [directional_research.json](../results/directional_research.json).
- Reanalisador: [directional_trade_reanalysis.py](../src/jev_trader/directional_trade_reanalysis.py).
- Relatório fonte SHA-256: `54bb3daf09aab91e810e9f8bdaaf0f23a7301cc963dd602ae36fb84163d6fdd6`.
- Hash de fontes de dados derivativas registrado no relatório fonte: `916a8a2363009c3f5ce23799c28c0dbd0974b6adff1f3df412c91ffffe510e1d`.
- Script usado na reanálise SHA-256: `180080bec0696e94d9c824cee4f3d54e3e9343a0040ce5f3df4cb31f74bf03af`.
- Arquivos de dados registrados: 536.

Nenhuma ordem real foi enviada ou autorizada por estes resultados.
