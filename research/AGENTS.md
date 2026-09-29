# AGENTS.md — Binance MultiStrategy v0.1

**Critérios de estratégia atualizados em 28/09/2026:** consultar
`docs/OBJETIVOS_ATUAIS_2026-09-28.md`. Essa atualização substitui a meta anterior de
drawdown máximo e torna a taxa de acerto de 70% uma preferência flexível; EV líquido e
payoff são os critérios econômicos definidos pelo usuário. Código e configurações já
foram alinhados; resultados do primeiro treinamento GPU estão em
`docs/RESULTADOS_TREINAMENTO_GPU_2026-09-28.md` e ainda não demonstram a meta.

## Intenção do usuário

Implementar e validar o núcleo multiestratégia v0.1 para Binance Spot/USD-M com dados
reais, ML numérico e avaliação cronológica. Melhorar em ciclos mensuráveis, buscando
lucro líquido consistente e menor drawdown.
Só depois experimentar Laya especializado ou Jev para verificar benefício incremental.
Não tornar esses modelos dependências iniciais nem presumir que agregam valor.

Leia `docs/HANDOFF_LOCAL.md` (revisão documental 2, 27/09/2026), `README.md` e
`docs/PROTOCOL.md` antes de implementar. Esta entrega altera documentação, não o código.

## Prioridades

1. Manter datasets e execuções de pesquisa auditáveis; não repetir testes Jev anteriores.
2. Comparar regras sem ML com o filtro numérico já existente; preservar ambos.
3. Corrigir/aperfeiçoar por hipóteses registradas e validação temporal, sem tuning no teste final.
4. Implementar observabilidade, coleta contínua, paper e, depois, demo/reconciliação.
5. Manter treinamento Laya e integração Jev fora desta etapa prioritária.

## Invariantes

- Indicadores, gatilhos, risco, stop e trailing ficam no código. Ausência de Laya/Jev
  não significa remover o classificador/regressor numérico da v0.1.
- Não perseguir 70% sacrificando resultado líquido ou risco. Não reintroduzir taxa de
  acerto ou drawdown como gate rígido; manter EV e payoff conforme o documento de objetivos.
  Registrar qualquer mudança nos gates adicionais de amostra e custos. Não inventar meta
  mensal de rentabilidade.
- Não chamar APIs pagas de modelos a cada decisão nesta fase.
- Não usar dados futuros, mascarar perdas, aumentar alavancagem para aprovar resultados
  nem executar busca ilimitada até encontrar um backtest favorável.
- Registrar experimentos, inclusive negativos; versionar dados/config/código/modelo.
- Paper diagnóstico não é produção. Nenhum gate autoriza ordens reais automaticamente.
- Preservar pesquisas existentes e instruções locais aplicáveis ao integrar o subprojeto.
- A execução de 28/09/2026 passou 57 testes de software; isso não prova rentabilidade.
  O resultado do treinamento e seus limites estão em `docs/RESULTADOS_TREINAMENTO_GPU_2026-09-28.md`.

## Primeira execução local

```powershell
uv sync --extra dev --extra gpu
uv run pytest -q
uv run multitrader --help
```

Entregar evidências do que foi executado, comparação com a referência, limitações e
próxima hipótese. Continuar a implementação/pesquisa autorizada sem pedir confirmação
para cada ajuste; não habilitar custos externos ou dinheiro real sem autorização.
