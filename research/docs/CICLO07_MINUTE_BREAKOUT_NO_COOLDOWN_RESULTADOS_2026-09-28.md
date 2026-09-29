# Ciclo 07 — resultados do breakout de 1m sem cooldown adicional

Executado em 28/09/2026 conforme o [protocolo congelado](CICLO07_MINUTE_BREAKOUT_NO_COOLDOWN_PROTOCOLO.md). Resultado: `rejected_no_cooldown_policy`; o C06 continua como a melhor hipótese exploratória, sem estratégia validada.

## Comparação pareada com o Ciclo 06

O protocolo mudou apenas o cooldown de candidatos de 15 para 1 minuto. O scanner mais denso também aumentou os rótulos disponíveis para cada atualização mensal do mesmo XGBoost.

| Métrica | C06: cooldown 15m | C07: cooldown 1m | Gate Rev02 |
|---|---:|---:|---:|
| Candidatos gerados | 6.416 | 15.410 | diagnóstico |
| Eventos na seleção | 1.977 | 4.441 | diagnóstico |
| Selecionados pelo modelo | 19 | 19 | diagnóstico |
| Trades executados | 11 | 11 | >=200 |
| Semanas ativas | 6 | 5 | >=8 |
| EV-base | **+1,262%** | −0,232% | >+1,2% |
| Acerto | 27,27% | 18,18% | preferência ~70% |
| Payoff | 10,17 | 2,55 | >=1 |
| Profit factor | 4,35 | 0,51 | >=1,25 |
| Drawdown máximo | 2,39% | 1,70% | medir, sem teto |
| PnL sob stress | **+US$ 380,50** | −US$ 124,40 | >0 |

O C07 não aumentou as entradas executadas e falhou gates de amostra, frequência, EV, PF e PnL de stress. Seu baseline sem filtro também perdeu: EV de −0,182%, PF 0,48 e drawdown de 53,88%; com custo dobrado, o EV foi −0,395% e o drawdown 78,69%. O stop de 15m permaneceu igual, mas não tornou rentável a regra sem filtro.

## Aprendizado sobre as mudanças

O número de candidatos na seleção mais que dobrou, mas o modelo continuou acima do cutoff em apenas 19 eventos e o portfólio executou os mesmos 11 trades que no C06. Só três entradas foram iguais nos dois portfólios; eram três perdas. O C06 tinha os maiores vencedores em 15/03 (+3,709%), 07/04 (+3,956%) e 19/08 (+11,144%), que o C07 não reproduziu. O novo portfólio teve apenas um ganho expressivo (+3,294% em ETH em 07/04); os outros dez resultados foram negativos ou próximos de zero. Portanto, o C06 continua sendo uma hipótese de cauda concentrada, não evidência de uma regra confiável.

No conjunto rotulado do C07, 12.069 de 15.393 janelas se sobrepõem a uma janela anterior (78,41%). A correlação de Pearson do score caiu de 0,140 no C06 para 0,038; o R² foi −0,054 e o MAE de 0,551% superou o baseline constante de 0,535%. A mudança de cooldown também altera o conjunto de treino mensal; assim, este experimento mede o efeito total da política de cooldown e retreino denso. Ele não separa o efeito do scanner em um modelo congelado.

## Decisão

Rejeitar cooldown de 1 minuto sob esta configuração. Preservar o stop ATR de 15m e o portfólio C06 como componentes exploratórios; não alterar o cutoff de 1,2% com a mesma janela. A baixa frequência não foi resolvida por criar mais candidatos. O novo gargalo mensurável é a representação repetida de movimentos quase idênticos no treino: 78,41% de sobreposição e pior discriminação do score. A próxima experiência isolará pesos por unicidade temporal no treino, mantendo scanner de 1m, stop ATR15, saída EMA21/15m, cutoff, sizing, execução e mercado.

Todos os replays usam uma janela histórica já examinada. Nenhum resultado é validação independente nem autoriza paper ou ordens reais. Nenhuma ordem real foi enviada.

## Proveniência

- Relatório JSON: [`cycle07_minute_breakout_no_cooldown_2026-09-28/research.json`](../results/cycle07_minute_breakout_no_cooldown_2026-09-28/research.json); hashes e ledger no `research/EXPERIMENTS.jsonl`.
- Script: `research/scripts/cycle07_minute_breakout_no_cooldown.py`.
- Protocolo: SHA-256 `7867c51f796b3b91af4330a648c4f2d114268042a3c0b448e32e73f781b824fc`.
- Oito folds mensais treinaram em `device=cuda:0`, `tree_method=hist`.
- Os dois testes determinísticos passaram antes do replay.
