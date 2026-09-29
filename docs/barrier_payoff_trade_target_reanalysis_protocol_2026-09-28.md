# Protocolo: recontagem do replay de barreiras pelas metas por operação

## Escopo

Não executar nem ajustar a estratégia de barreiras. Reutilizar somente as 32 séries de fills já arquivadas em `results/barrier_payoff_research.json`, geradas pelo replay real de BTCUSDT Spot. O estudo original usou stop de 1 ATR, alvo de 2 ATR, timeout de oito horas, custos de 0,12%/0,24% por lado e alocações de 50%/100%. Este arquivo reavalia esses mesmos fills após a mudança de meta do projeto.

## Métricas por operação

Parear cada evento `enter` com o evento `exit` de mesmo `entry_ms`. Retorno líquido percentual sobre o notional inicial = `(price_pnl - taxa de entrada - taxa de saída) / notional de entrada * 100`; o mercado é Spot, sem funding. Vitória exige retorno líquido estritamente positivo; payoff é ganho médio líquido dividido pela perda média líquida absoluta; EV é a média de retornos líquidos. Não reconstruir nem alterar decisões.

Recalcular acerto, payoff, EV e quantidade no total do período `later` e agrupar operações por ano de entrada apenas como diagnóstico. Para o gate de drawdown usar os campos preservados no replay original: máximo drawdown marcado e limite adverso intrabar. Um cenário só passa se tiver pelo menos 30 operações, acerto `>=70%`, payoff `>=1`, EV `>1,2%` por notional e ambos os drawdowns `<=10%`. Comparar cenários-base e estressado sem escolher vencedor pela recontagem.

## Proveniência e limites

O relatório deve registrar hashes do replay-fonte e deste código/protocolo, reconciliar quantidade de pares de fills com `entries` e confirmar a soma do PnL líquido com os eventos. Os intervalos e ativos já foram examinados em estudos anteriores; isto é reclassificação retrospectiva, não nova validação. Nenhum dado de mercado será baixado, nenhuma chamada JEV ocorrerá e nenhuma ordem será enviada.

