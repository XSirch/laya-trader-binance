# Revisão documental 2 — 27/09/2026

## Motivo

O usuário confirmou implementar e evoluir primeiro a v0.1 multiestratégia para buscar
lucro líquido razoável. Treinar Laya ou usar Jev fica para uma etapa posterior, mediante
comparação que demonstre se há melhoria real.

## Mudanças

- `docs/HANDOFF_LOCAL.md`: direção, responsabilidades, sequência de implementação,
  melhoria por hipóteses, evidências exigidas e protocolo futuro de comparação.
- `AGENTS.md`: novo ponto de entrada para agentes dentro deste subprojeto.
- `README.md`: resumo da intenção e identificação da revisão documental.
- `docs/PROTOCOL.md`: referência à nova direção, sem alterar as regras existentes.
- `MANIFEST.sha256`: recalculado para os arquivos desta distribuição.

## Não alterado / não realizado

Código Python, testes, configurações, dependências e versão 0.1.0 permanecem inalterados.
O relatório `docs/VALIDACAO_SOFTWARE.json` e o log de pytest são registros históricos
preservados. Não foram reexecutados testes de software nem treinamento nesta revisão.
Não houve download de dados de mercado, novo backtest, ajuste dos gates, ativação de
Laya/Jev, ordem, conexão com conta ou modificação remota do GitHub.

A revisão foi verificada por comparação byte a byte dos arquivos preservados,
integridade do ZIP, equivalência entre o handoff avulso e o interno e manifestos SHA256.
Isso valida a distribuição documental, não rentabilidade nem operação do robô.
