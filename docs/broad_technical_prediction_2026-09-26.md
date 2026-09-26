# Comparação com todos os indicadores técnicos disponíveis

A ampliação para 60 entradas não comprovou uma estratégia consistente. Foram usados os dez fatores econômicos e os 50 campos numéricos/booleanos do módulo de indicadores diários: médias, RSI, MACD, ADX/DI, Bollinger, ATR, fluxo, volume, estrutura e Fibonacci. Nenhum campo disponível dessa família foi selecionado ou removido com base no resultado posterior. Não houve chamada adicional ao JEV.

## Resultado da seleção

As seis variantes técnicas perderam no desenvolvimento de 2022–2023. A de maior retorno entre as variantes de trading foi ridge 0,1 com valores iguais e hedge de beta, mas ela perdeu 2,91%. Sua identificação como selecionada serve apenas à comparação: escolher a menos negativa não autoriza operar. A referência em caixa teve retorno zero.

| Variante técnica | Desenvolvimento | 2024 | Janeiro–julho/2026 |
| --- | ---: | ---: | ---: |
| 0,1; valores iguais | -2,91% | -1,35% | -2,92% |
| 0,1; inverso da volatilidade | -4,03% | -3,61% | -1,60% |
| 1; valores iguais | -7,79% | -3,62% | +0,52% |
| 1; inverso da volatilidade | -7,47% | -9,20% | +1,51% |
| 10; valores iguais | -7,24% | -8,01% | -2,84% |
| 10; inverso da volatilidade | -7,20% | -12,74% | +1,97% |

Valores após custo de 0,15% por lado e funding. Os cenários de 0,10% e 0,30% também estão registrados. Houve 214 ajustes semanais; cada treino usa somente alvos encerrados antes do sinal, com no mínimo 52 semanas anteriores. Os testes alteram dados futuros e verificam que os sinais passados permanecem idênticos.

## Encerramento de contratos: evidência adicional

O replay estrito continua interrompendo quando há posição em MKR sem preço de encerramento verificado. O resultado estrito permanece preservado; foi acrescentado um cenário separado, condicionado à regra publicada de liquidação.

A [regra oficial publicada em novembro de 2024](https://www.binance.com/en-AU/support/announcement/detail/4bcabddf0e81423ebca242e185bf157d) passou a usar a média dos índices de preço de cada segundo dos 30 minutos anteriores à liquidação, incluindo contratos retirados. Os arquivos oficiais do índice, com candles de um minuto e checksum verificado, permitem limitar essa média pela média dos mínimos e pela média dos máximos dos 30 candles. Não se usa a média dos fechamentos como se fosse o preço real.

As faixas calculadas são 0,76159817–0,76345808 para EOS e 1.648,84637072–1.650,78507561 para MKR. A simulação usa a ponta adversa à posição e cobra o custo de saída. O cenário assume que a regra geral foi aplicada sem exceção e que os extremos dos candles cobrem as amostras usadas na liquidação. Ele não comprova uma transação nem o preço exato de settlement. Esses limites continuam explícitos nos resultados.

## Comparação sob a hipótese de liquidação

| Seleção pelo desenvolvimento | Retorno 2024–julho/2026 | Queda máxima horária | Meses positivos | Intervalo anualizado de 95% |
| --- | ---: | ---: | ---: | ---: |
| Dez fatores; ridge 0,1; inverso da volatilidade | +3,79% | 13,11% | 22/31 | -10,32% a +14,53% |
| Sessenta entradas; ridge 0,1; valores iguais | +6,24% | 11,79% | 14/31 | -9,36% a +15,82% |

Os intervalos usam blocos de 30 dias e 2.000 reamostragens. Os p-valores da estatística máxima da família foram aproximadamente 0,28 e 0,61, respectivamente. Eles são condicionados ao cenário de liquidação e corrigem apenas as variantes de cada família, não todo o histórico desta pesquisa. Nenhum intervalo exclui retorno zero.

A variante econômica de valores iguais teve +17,14% no agregado posterior, mas não era a escolhida no desenvolvimento e perdeu em 2026. Selecioná-la agora pelo agregado posterior seria uma nova escolha retrospectiva, não uma confirmação independente.

## Conclusão da rodada

Acrescentar indicadores a uma regressão linear não foi suficiente. Na variante técnica 0,1, o erro de previsão agregado de 2024–julho/2026 ficou maior que o da previsão zero, com R² de -0,00195. Os resultados não sustentam declaração de lucratividade consistente nem execução real.

A próxima investigação separará a hipótese de interações não lineares da hipótese linear já testada, sem remover períodos ou ativos desfavoráveis. Será necessário contabilizar essa nova família na avaliação de múltiplas tentativas e preservar a distinção entre diagnóstico retrospectivo e confirmação futura.

Reprodução do replay estrito: `python -m jev_trader.broad_technical`. O cenário com faixas de liquidação usa `run(feature_bundle, 'technical', settlement_scenario=True)` de `broad_prediction`. As fontes e os limites estão em `settlement_bounds_2026-09-26.json`; os resultados estritos e condicionais têm arquivos separados.
