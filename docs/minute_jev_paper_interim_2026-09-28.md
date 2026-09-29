# Snapshot intermediário do paper JEV

Captura somente para acompanhamento do processo prospectivo ativo. Não encerra nem altera o experimento; `events.jsonl` continua crescendo.

## Estado verificado

- Captura UTC: `2026-09-28T21:04:28.328Z`.
- Série: `minute_jev_paper_20260927`; processo PID `26824`, fase `waiting`, heartbeat com 1,5 s de idade.
- Duração: 26,99 h decorridas de 72 h, com cerca de 45,01 h restantes.
- Configuração congelada: SHA-256 `a6799d668330ab0e3e03f237d8610af82080eee4f4229b7a7cd049e12551b98c`.
- Ordens reais: desativadas (`live_orders_enabled=false`). Gasto da API: US$ 0,22975113 de US$ 1,00.

## Evidência do ledger

`events.jsonl` tinha 3.229 registros e 15.008.727 bytes. A cadeia SHA-256 foi verificada integralmente e resultou em `b15b96a8411bbf545d22d3cc6c8d3b8e13416183a7c9d95e49e87b909a081823`.

| Medida intermediária | Valor |
|---|---:|
| Minutos programados decorridos | 1.619 |
| Minutos processados e válidos | 1.593 |
| Cobertura até o snapshot | 98,3941% |
| Respostas de minuto perdidas | 25: 12 HTTP, 8 URL e 5 timeout |
| Ações JEV | 1.593 `IDLE` |
| Execuções simuladas | 1.593 `IDLE` |
| Entradas / round trips fechados | 0 / 0 |
| Caixa / equity / PnL realizado | 100 / 100 / 0 USDT |
| Drawdown observado / adverso | 0% / 0% |

A cobertura final do protocolo precisa ser de pelo menos 99% de 4.320 minutos. Isso permite no máximo 43 minutos sem observação; 26 já faltavam no denominador decorrido deste snapshot, restando margem para no máximo 17 perdas adicionais. Os erros não recebem retry, conforme o protocolo congelado.

## Interpretação

Este snapshot não estima EV, payoff ou taxa de acerto: não houve operação fechada. O `IDLE` em todas as decisões válidas indica abstinência total até aqui, não evidência de lucro. Mesmo uma triagem de 72 h aprovada seria apenas screening de BTCUSDT Spot, longe da amostra de 200 operações e da consistência entre regimes e pares requerida pelo objetivo.

O próximo ponto de avaliação é a expiração da mesma série. Preservar o processo e o ledger atuais; não iniciar uma segunda cópia.

Os arquivos `target_metrics.json` e `target_metrics.md` na série foram gravados em 27/09 às 18:18 e cobrem apenas 191 minutos processados; não representam o estado atual nem o resultado final de 72 h.

## Rechecagem UTC 21:09:56

O PID `26824` permanecia vivo e o ledger estável passou novamente pela verificação completa da cadeia: 3.239 registros, SHA-256 `723c8339111d7f2292d01f8acbd47332f7896a1e18cb8c77df6d1c6a425e923f`. Havia 1.598 minutos válidos de 1.625 esperados até esse instante (98,3384%); os 25 registros de falha continuavam distribuídos em 12 `HTTPError`, 8 `URLError` e 5 `TimeoutError`. A margem calculada para o gate final era de 16 minutos perdidos adicionais.

As 1.598 decisões continuavam `IDLE`, sem entrada ou round trip; a maior probabilidade de compra observada era 0,40, abaixo do limiar 0,60. O gasto acumulado da API era US$ 0,230463576, sem ordens reais habilitadas. A próxima leitura deve continuar usando o mesmo PID, configuração e ledger.

## Rechecagem UTC 21:12:44

O mesmo processo seguia ativo. A leitura estável verificou 3.245 registros de ledger, SHA-256 `183458568149278905dd5d7503343f422675747b0384bf5ae3bc82c8aa56f22e`, e 1.601 minutos válidos de 1.628 esperados (98,3415%). Continuavam 27 minutos sem resultado válido e 16 perdas adicionais toleráveis até o limite de cobertura final; as 25 falhas de rede não aumentaram.

As 1.601 decisões válidas ainda eram `IDLE`, com zero round trips. O gasto acumulado era US$ 0,23089105 e ordens reais seguiam desativadas. O processo permanece no modo `waiting`, sem mudança de modelo, threshold ou regra.

## Rechecagem UTC 21:15:56

O PID `26824` continuava ativo em `waiting`, com heartbeat de 9,2 s, mesma configuração congelada e `live_orders_enabled=false`. A leitura estável validou os 3.251 registros; o ledger tinha 15.111.449 bytes e SHA-256 `a3a2d45a6a202924164829f3a7472c118ee7e60b34bd8819e7d37f93479a0700`.

Até o heartbeat, havia 1.604 minutos válidos de 1.631 esperados (98,3446%), portanto 27 minutos sem resposta válida. Permanecem 16 perdas adicionais de margem até o limite final de 43. Os erros não aumentaram: 12 `HTTPError`, 8 `URLError` e 5 `TimeoutError`. O gasto registrado era US$ 0,231318024.

As 1.604 decisões válidas continuavam `IDLE`; a maior probabilidade de `BUY` observada permanecia em 0,40, abaixo do limiar 0,60. Não houve entrada nem round trip: saldo e equity seguem em 100 USDT, sem PnL ou drawdown observado. Assim, não há amostra para estimar EV, payoff ou acerto.
