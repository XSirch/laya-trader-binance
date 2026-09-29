# Ciclo 18 — inicialização do paper prospectivo

**Registro:** 29/09/2026, 01:38 UTC  
**Escopo:** coletor paper para futuros perpétuos USDⓈ-M; apenas endpoints públicos GET. Nenhuma credencial, endpoint de ordem ou ordem real foi usado.

## Resultado desta captura

O coletor foi inicializado antes da primeira janela elegível. A captura `paper_tick` de 29/09/2026 às 01:34:54 UTC registrou o cutoff de dados de 00:00 UTC e terminou às 01:34:55.121 UTC. A primeira decisão programada continua sendo 05/10/2026 às 01:00 UTC. Nesta execução o estado foi `not_scheduled`: não houve inferência, probabilidades, alvos, entrada ou trade paper.

Dos 20 símbolos congelados, 18 estavam ativos. `EOSUSDT` estava ausente de `exchangeInfo` e `MKRUSDT` constava como `SETTLING`; nenhum contrato foi adicionado para compensar as ausências. Os 18 símbolos ativos receberam 212 candles diários e 51 registros históricos de funding por símbolo, lidos dos arquivos locais verificados por manifesto. A origem local foi o manifesto de arquivo SHA-256 `11f72aa37a646cf46e7904337aced83e2aa06c052377f07c7596e0287465a05a`; o coletor leu 2.719 arquivos sem escrever no cache compartilhado.

O ledger paper tem quatro registros encadeados. Os 80 recibos das chamadas públicas e os respectivos arquivos brutos passaram a conferência de SHA-256. O registro final é a sequência 4, hash `9144da708a7216c34480e00532c99af238895eee728316c20e026ca6460ad104`. As contas base e stress iniciaram com US$ 10.000 cada, sem posições, trades, custos ou PnL. Drawdown 0% neste ponto representa apenas o estado inicial, não evidência de baixo risco. EV, payoff, profit factor e acerto permanecem indefinidos; o gate de amostra não foi satisfeito.

## Congelamento e limites

A configuração paper tem SHA-256 `9d92835b4b70b6fe175a9fa88c40d1b2f182e8d978529e398abc7ec0c220a71f`; o modelo congelado tem SHA-256 `13c1b2dbd59a56d29ed172a5abb390159da0b6528989993b02641c1e7f9ad606`. Este tick não reajustou o modelo e não usou GPU. O protocolo mantém o cutoff de score em 0,70, os custos base/stress registrados, o drawdown sem teto fixo e a exigência de pelo menos 200 episódios completos e únicos em oito ou mais semanas ativas por variante e mercado.

Este é um registro de infraestrutura e início de coleta, não uma avaliação da estratégia nem uma descoberta nova de alfa. O candidato foi selecionado após inspeção histórica e a evidência retrospectiva continua exploratória. A validação depende de decisões e episódios prospectivos completos; nenhuma configuração habilita ordens reais.

## Artefatos

- Protocolo: [Ciclo 18 — filtro HGB em baixa volatilidade](CICLO18_META_FILTRO_HGB_BAIXA_VOLATILIDADE_FORWARD_PROTOCOLO_2026-09-29.md)
- Relatório do modelo congelado: [resultados HGB](CICLO18_MODELO_HGB_RESULTADOS_2026-09-29.md)
- Coletor e contabilidade: `src/jev_trader/lowvol_hgb_paper.py`, `src/jev_trader/lowvol_hgb_account.py`
- Configuração e cadeia paper: `research/results/cycle18_lowvol_hgb_forward/paper/`
- Ledger de experimentos: `research/EXPERIMENTS.jsonl`
- Especificação pública de market data: [Binance USDⓈ-M Futures Market Data REST API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api)


## Agendamento local da coleta paper

Em 29/09/2026 foi registrada a tarefa `C18-LowVol-HGB-Paper`, com execução semanal aos domingos às 22:00 no fuso de São Paulo, equivalente a segunda-feira 01:00 UTC. O Agendador confirmou a próxima execução para 04/10/2026 às 22:00 local. A tarefa executa somente `scripts/run_c18_lowvol_hgb_paper_tick.cmd`, que chama o tick C18 já congelado e grava a saída em `research/results/cycle18_lowvol_hgb_forward/paper/scheduled_runner.log`.

A tarefa usa sessão interativa, não acorda o computador, não tenta recuperar uma janela perdida, permite início e continuidade na bateria e termina após dez minutos. O Agendador não filtra conexão de rede: sem internet, o runner registra a falha e não produz decisão. No momento do registro, a tarefa estava habilitada e pronta, sem execução ou nova observação de mercado. Ordens reais continuam desabilitadas.

Definição XML conferida: `research/results/cycle18_lowvol_hgb_forward/paper/task_definition.xml` (SHA-256 `7294e2023ca630aef17d0329ae89a8c9d44b831b2524c8a3c29a302022969c61`). O estado operacional foi acrescentado ao ledger; qualquer métrica de trading só poderá ser calculada após os ticks e episódios prospectivos.
