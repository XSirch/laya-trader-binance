# Robustez à retirada de um ativo

O replay recalculou rankings e posições ao retirar cada um dos vinte ativos, mantendo sinais, regras de risco e custos. Foram 84 simulações: 21 universos, com e sem trailing de carteira de 4%, em duas janelas. Todas terminaram sem preço pendente de posição; as quatro simulações com universo completo reproduziram os resultados anteriores de retorno, queda máxima e custos com tolerância de 1e-10.

Nas vinte exclusões, o retorno acumulado de janeiro/2024 a 26/setembro/2026 permaneceu positivo: de +19,95% a +41,54% sem trailing e de +28,16% a +54,09% com trailing. Esses extremos descrevem sensibilidade, não uma seleção de carteira. O trailing elevou o retorno agregado em dezoito das vinte comparações; retirar AAVE ou XLM produziu as duas exceções.

A janela independente de agosto–setembro/2026 permaneceu negativa em todas as exclusões, com ou sem trailing. Com trailing, os resultados ficaram entre -7,09% e -2,75%. Logo, retirar um ativo isolado não resolveu a perda recente. Não há fundamento neste teste para escolher uma exclusão vencedora e anunciá-la como estratégia consistente.

Retirar BTC tem interpretação especial: sua ausência impede a proteção do componente de carry, que fica em caixa pelas regras existentes. Essa simulação retornou +31,06% no agregado e -2,75% na janela recente com trailing, com menor exposição estrutural. Os indicadores dos demais ativos mantiveram o histórico original; foi alterada somente a disponibilidade para negociação.

O benefício agregado não depende exclusivamente da presença de um único ativo, mas esse resultado ainda não comprova consistência entre períodos. A próxima investigação deve abordar a deterioração conjunta dos sinais ou a validação em dados novos, sem remover retrospectivamente os ativos perdedores. Os vinte resultados permanecem no relatório para evitar uma seleção posterior conveniente.

Evidência: `trailing_universe_2026-09-26.json`, com hashes do código, protocolo, candidato fixado e relatório completo. Reprodução: `python -m jev_trader.trailing_universe`. Nenhuma chamada ao JEV ou ordem real foi realizada.
