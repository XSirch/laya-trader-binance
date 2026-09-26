# Controles causais de exposição por contexto

Foram avaliadas oito variantes da carteira multifatorial: referência, escala de volatilidade, concordância técnica e produto dos controles, cada uma com e sem trailing de carteira de 4%. A entrada preservou o pacote de sessenta campos econômicos e técnicos; a fórmula de concordância agregou seis grupos de indicadores, incluindo médias, momentum, participação, estrutura e Fibonacci. Nem todos os campos recebem peso na fórmula: o protocolo e o código explicitam quais participam, sem afirmar que a disponibilidade de um indicador por si só melhora a previsão.

A escolha mecânica pelo maior retorno positivo de 2022–2023 selecionou `reference_none`, com +20,44%, antes de avaliar os períodos posteriores nesta execução. O registro da seleção está em `regime_risk_selection_2026-09-26.json`. O pesquisador já havia observado períodos posteriores em outras pesquisas; essa separação mecânica não torna os resultados prospectivos.

| Variante | Desenvolvimento 2022–2023 | Janeiro/2024–setembro/2026 | Agosto–setembro/2026 |
| --- | ---: | ---: | ---: |
| Referência | +20,44% | +29,16% | -4,59% |
| Referência + trailing | +16,09% | +37,57% | -6,05% |
| Volatilidade | +16,06% | +24,27% | -4,07% |
| Volatilidade + trailing | +12,39% | +29,46% | -4,74% |
| Concordância técnica | +12,52% | +21,00% | -2,90% |
| Concordância + trailing | +10,74% | +21,64% | -3,41% |
| Ambos os controles | +9,95% | +17,70% | -2,53% |
| Ambos + trailing | +10,08% | +17,76% | -2,53% |

Retornos líquidos simulados com custo de 0,15% por lado. Foram também executados todos os cenários a 0,30%, preservados no JSON. As janelas começam separadamente em caixa; o agregado mantém a trajetória contínua, portanto não é o produto direto dos retornos das janelas independentes. Não houve falha de preço mantido em posição.

As políticas reduziram perdas recentes, porém todas continuaram negativas nessa janela e nenhuma superou a referência no desenvolvimento pelo critério previamente definido. A melhora na magnitude da perda não demonstra previsão melhor: reduzir exposição pode reduzir tanto ganhos quanto perdas. Comparações futuras de qualidade do sinal devem incluir uma referência com redução constante de exposição, para separar informação incremental de mera redução de risco.

Manter a estratégia em pesquisa. Não trocar retrospectivamente a variante selecionada nem recalibrar os limites para tornar positiva a janela recente. Esta hipótese não demonstrou a consistência buscada. Nenhuma chamada adicional ao JEV ou ordem real foi realizada.

Reprodução: `python -m jev_trader.regime_risk`. Protocolo: `regime_risk_protocol_2026-09-26.md`. Resultados: `regime_risk_2026-09-26.json`.
