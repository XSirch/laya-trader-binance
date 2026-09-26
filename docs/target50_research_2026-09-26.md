# Resultado da grade de exposição e trailing para 50%/10%

Nenhum dos 48 cenários atingiu simultaneamente CAGR líquido de pelo menos 50% e drawdown horário de no máximo 10%. O objetivo definido pelo usuário permanece pendente. Esta conclusão se limita à grade fixada no protocolo; não demonstra que toda estratégia de trading seja incapaz de atender à meta.

Foram usados os mesmos sinais de baixa volatilidade e carry protegido, com multiplicadores de exposição de 0,5, 1, 2, 3, 4 e 6, sem trailing ou com distância de 1%, 2% e 4%, a custos de 0,15% e 0,30% por lado. Cada cenário recalculou a trajetória completa de 1/janeiro/2024 a 26/setembro/2026, incluindo funding e liquidação terminal. O período tem 999 dias; retorno acumulado e CAGR são medidas distintas.

## O aumento de exposição não resolveu

Exemplos da grade a custo de 0,15% por lado, todos sobre a carteira inteira:

| Cenário | Retorno acumulado | CAGR líquido | Drawdown horário |
| --- | ---: | ---: | ---: |
| Exposição original, trailing 4% | +37,57% | +12,36% | 7,43% |
| Exposição 2 vezes maior, trailing 4% | +36,52% | +12,05% | 17,38% |
| Exposição 4 vezes maior, trailing 4% | -38,47% | -16,26% | 48,55% |
| Exposição 6 vezes maior, sem trailing | +171,91% | +44,12% | 66,35% |

O último cenário teve o maior CAGR da grade, ainda inferior a 50%, e permitia exposição bruta alvo de até 300% do patrimônio apenas no replay. Seu limite adverso intrahorário chegou a 70,09%. Não se trata de parâmetro escolhido para operar. A carteira prospectiva continua com a exposição original de até 50%.

Com trailing de 4%, os acionamentos por carteira passaram de 10 na exposição original para 39 com exposição dobrada. As taxas acumuladas passaram de 6,74% para 21,58% do capital inicial. A combinação de saídas, reentradas e custos impede tratar retorno e risco como múltiplos lineares. Um stop por ciclo também não limita o drawdown acumulado da série inteira: várias perdas sucessivas podem ultrapassar a distância do gatilho.

Entre os cenários da grade com queda horária de até 10%, o maior CAGR a custo de 0,15% foi o da própria referência com trailing de 4%, 12,36%. A custo de 0,30%, o maior CAGR que respeitou esse limite foi 4,59%, com metade da exposição e trailing de 2%; sua queda foi 5,26%. São descrições posteriores da grade, sem seleção de novo vencedor. No cenário original com trailing de 4%, dobrar o custo reduziu o CAGR para 9,12% e levou a queda a 10,33%, ultrapassando o limite do usuário.

## Evidência e limites

Os quatro cenários de referência, com escala 1 e sem stop ou trailing de 4%, reproduziram retorno, drawdown, taxas e contagem de saídas do relatório anterior com diferença zero. Os hashes de protocolo, fontes congeladas, código deste experimento, relatório de referência e manifests permaneceram iguais entre início e fim. Foram verificados 4.182 arquivos/fontes diárias, 1.283 horárias e 54 respostas REST já em cache. Não houve nova aquisição de rede, chamada paga, alteração de regra em execução ou envio de ordens.

Não houve insolvência ou acionamento do indicador de estresse de margem nestes cenários. Isso não valida a margem para uma conta real: o motor não reproduz faixas de manutenção, liquidação ou taxas de liquidação da corretora. O drawdown horário pode perder extremos entre observações. O limite adverso combina extremos simultâneos e não é uma reconstrução de preenchimentos intrahorários. Impostos e condições específicas de conta estão fora dos custos modelados.

Reprodução: `python -m jev_trader.target50_research`. O protocolo está em `target50_protocol_2026-09-26.md`, a síntese completa dos 48 cenários em `target50_research_2026-09-26.json` e as trajetórias em `results/target50_research.json`, com hash registrado na síntese. Os resultados continuam retrospectivos e sujeitos ao histórico de pesquisa já realizado.

O próximo avanço econômico precisa vir de outra regra ou de uma melhora demonstrável nos sinais e na diversificação. Esta grade não justifica ampliar risco da carteira atual para perseguir a meta. O JEV segue limitado a pontuar aderência e ainda não foi testado nesta carteira broad de funding e posições long/short; o experimento anterior, com 103 campos de quatro ativos spot, é outro contrato de decisão e não pode ser reaproveitado como evidência desta hipótese.
