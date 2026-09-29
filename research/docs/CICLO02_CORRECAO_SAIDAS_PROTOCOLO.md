# CICLO 02 — correção de roteamento dos planos de saída

Registrado em 28/09/2026, antes da reexecução corrigida. Esta é uma correção de implementação do protocolo principal, não uma estratégia ou busca de parâmetros nova.

## Falha observada

O código declarou modos curtos (`fixed`, `trailing`, `trend_loss`) e descrições longas no pré-registro, mas passou a descrição longa para o simulador, que comparava somente os modos curtos. Com isso, a primeira execução usou stop inicial e saída por tempo em todos os três planos. O arquivo de rótulos e os hashes dos modelos eram idênticos entre as saídas de cada família/horizonte. A primeira execução, a sensibilidade de threshold e a análise de importância derivada dela ficam invalidadas para o protocolo pretendido; os artefatos originais serão preservados para auditoria.

## Correção e gates de implementação

- Passar um identificador canônico de saída em todo o caminho de simulação: rotulagem, baseline, avaliação de carteira e smoke.
- Rejeitar identificadores desconhecidos em vez de cair silenciosamente no stop/tempo.
- Adicionar testes determinísticos para alvo fixo, trailing stop, saída por perda da EMA21 e rejeição de uma descrição longa no lugar do modo canônico.
- Rodar os 12 smoke cases de cada mercado. Verificar se as razões de saída implementadas correspondem ao modo pedido.
- Se as saídas completas ainda produzirem rótulos idênticos em todos os três modos para qualquer variante, interromper antes do treino e investigar.

## Reexecução congelada

Manter o universo Spot e USD-M, símbolos, entradas, features, horizontes, custos, funding, sizing, thresholds, janelas, purge/embargo e gates do [pré-registro principal](CICLO02_PRE_REGISTRO.md). Treinar HGB CPU e XGBoost CUDA novamente sobre os rótulos corretos e salvar em um diretório novo, sem sobrescrever a execução invalidada. Nenhuma ordem real.

A avaliação corrigida continua retrospectiva e não vira holdout intocado. A sensibilidade pós-hoc e os diagnósticos de feature gain anteriores não podem ser reutilizados como resultados dos planos de saída corrigidos. Qualquer sensibilidade futura deve usar modelos e rótulos corrigidos e continuar identificada como pós-hoc.

## Resultado da reexecução — 28/09/2026

Concluída em `research/results/cycle02_multiframe_corrected_2026-09-28/`. Os 8 grupos tiveram 3 hashes de rótulo distintos antes do treino; foram treinados 24 HGB CPU e 24 XGBoost CUDA; nenhuma das 72 comparações ou 480 combinações de threshold passou os gates. O máximo foi 99 trades por threshold, abaixo da amostra mínima. A auditoria do relatório e os motivos completos estão em [CICLO02_RESULTADOS_2026-09-28.md](CICLO02_RESULTADOS_2026-09-28.md). O resultado segue histórico e não autoriza paper ou ordens reais.
