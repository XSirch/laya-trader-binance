# Teste de capacidade das oportunidades C06 — protocolo

Registrado antes do novo cálculo em 28/09/2026. Tipo: diagnóstico retrospectivo de capacidade; não é estratégia, aprovação econômica ou validação prospectiva.

## Pergunta e hipótese

O conjunto de candidatos do Ciclo 06, antes do filtro XGBoost, contém pelo menos 200 oportunidades completas cuja média líquida dos 200 maiores retornos excede estritamente 1,2% do nocional inicial? Um resultado acima do corte só mostra capacidade retrospectiva potencial. Um resultado igual ou inferior ao corte rejeita o filtro como solução para esse conjunto, essa política e essa janela.

## Escopo congelado

- Mercado: futuros perpétuos Binance USD-M, universo C06 fixado em BTCUSDT e ETHUSDT.
- Janela histórica de seleção já examinada: sinal a partir de `2026-01-02T00:00:00Z`, antes de `2026-08-31T00:00:00Z`; a janela de resultados termina em `2026-09-01T00:00:00Z`.
- Todos os candidatos causais do scanner C06 entram, inclusive os rejeitados pelo XGBoost e os que perderiam a regra de posição global. Não se treinam modelos e não se reexecuta a seleção do filtro.
- Entrada na abertura do minuto seguinte; breakout dos 300 minutos completos anteriores, volume de pelo menos 1,3 vez a mediana dos mesmos 300 minutos, contexto 1h/4h e cooldown de 15 minutos por símbolo/direção.
- Política de saída C06 fixa: `trend_loss`, stop inicial de 1 ATR de 15m já fechado, saída por stop ou perda da EMA21 de 15m, e limite de 1.440 minutos. O campo `target_r=1.5` do candidato não é usado pelo modo `trend_loss`.
- Custos USD-M: taxa de 5 bp e slippage de 5 bp por lado na base; ambos dobrados no stress. Usar somente funding observado e o cálculo conservador do simulador.
- Considerar um resultado somente se o rótulo for completo, finito e terminar no máximo em `2026-09-01T00:00:00Z`, incluindo o fechamento da última vela observada. Não preencher dados ausentes, não usar MFE e não transformar candidatos incompletos em zero.

## Cálculo pré-fixado

1. Carregar e validar a série consolidada e seu manifesto; preservar os hashes de dados e código abaixo.
2. Regenerar o scanner e os desfechos com as funções existentes do Ciclo 06/Ciclo 02, sem chamar a rotina de treino. A saída de resultados C06 não está presente no worktree atual, então esta etapa reconstrói somente candidatos e seus desfechos fixos a partir dos candles verificados.
3. Deduplicar por `candidate_id`; falhar se qualquer retorno incluído for ausente ou não finito. Reportar candidatos brutos, completos, excluídos e duplicados.
4. Publicar contagem e métricas para o universo USD-M C06, além de cortes descritivos por símbolo e por símbolo/direção. Não agregar outro mercado, janela, backend, regra de saída ou cenário de custo.
5. Ordenar o universo principal por retorno-base líquido decrescente, usando `candidate_id` como desempate determinístico. A média dos 200 primeiros retornos-base é o limite superior relaxado. Na mesma coorte desses 200, calcular EV sob stress. Também informar, separadamente, a média dos 200 maiores retornos sob stress, se houver 200.
6. Informar semanas ativas, participação por símbolo/direção, concentração dos maiores retornos e sobreposição temporal. O cálculo relaxado permite que os 200 eventos sejam temporalmente incompatíveis; não estima drawdown de carteira nem execução simultânea.

Unidades: retornos são frações do nocional de entrada no cálculo e percentuais na tabela. `0.012` equivale a 1,2%. O limite dos 200 maiores não é estimativa de EV realizável, não satisfaz os gates de payoff/PF por si só e não escolhe um cutoff utilizável.

## Limitações e segurança

Todos os dados deste intervalo já foram examinados no Ciclo 06; o resultado é retrospectivo e contaminado para seleção de modelos. Pares e candidatos podem compartilhar períodos e risco de mercado; sinais simultâneos não são operações independentes. Um limite acima de 1,2% não prova que o ML consegue ordenar eventos, atingir 200 trades executáveis, manter payoff/PF ou reduzir drawdown. Um limite abaixo de 1,2% vale somente para este scanner, janela, universo e política de saída.

Nenhuma ordem real será enviada. Nenhum resultado deste diagnóstico habilita paper ou produção.

## Integridade de entradas

| Entrada | SHA-256 |
|---|---|
| Candles e marks USD-M consolidados | `cd09bd04a01c7de294438415df17fb26f86d346f10fc1c21ececbb4de0d84691` |
| Manifesto USD-M | `370539d1379221bb5a5cdbbb2ff9de30530616cd82b1b638c58f136110f651f4` |
| Scanner e integração C06 | `467b8e7f48f579f9cbe8083f834c79727786b341a54a252fab92de306ac8f432` |
| Simulador e pipeline C02 | `6727aa9555d4ed48715c8d632e1a95531bdff28a67e19f106855d6701db5c207` |
| Validação do dataset | `812b7f271e89c876a70472fec861d35179d1d812978f7e524415b17bd61f0ff2` |
| Indicadores | `9f2500419efba78df30eface72dc71e51455922a5ce0b95ed7521c5c4586bf39` |
| Motor de execução | `53806e958ea2bf26db57235f9f25faba6533cbc53dafe05c01a62552fef958d7` |

Artefatos de saída previstos: `research/results/opportunity_capacity_2026-09-28.json`, `research/results/opportunity_capacity_candidates_2026-09-28.csv` e `research/docs/OPPORTUNITY_CAPACITY_REPORT_2026-09-28.md`.
