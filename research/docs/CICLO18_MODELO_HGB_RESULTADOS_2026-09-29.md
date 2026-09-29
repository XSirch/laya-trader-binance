# Ciclo 18 — congelamento do modelo HGB

## Resultado do ajuste histórico único

O ajuste estático definido no protocolo C18 foi concluído em 29/09/2026, antes de qualquer score prospectivo. O treino usou 105 episódios completos com entrada entre 03/08/2024 e 01/08/2026 e saída estritamente antes de 01/08/2026: 61 rótulos de vitória e 44 de perda, com funding observado e custo histórico de stress de 0,15% por lado. O mínimo pré-registrado era 100; a amostra excedeu o piso por apenas cinco episódios e deve ser tratada como limitada.

O classificador e limiar permanecem os congelados no protocolo: `HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=15, l2_regularization=2.0, early_stopping=False, random_state=2026)` e `P(vitória) >= 0.70`. O ajuste usou CPU e limite de uma thread para evitar a criação de IPC negada pelo Windows. A limitação é operacional; nenhuma feature, classe, parâmetro do estimador, corte, custo ou período foi alterado.

## Integridade e limites

- Manifesto combinado histórico: SHA-256 `11f72aa37a646cf46e7904337aced83e2aa06c052377f07c7596e0287465a05a`; 4.182 entradas, com 2.719 arquivos de candles e funding usados nas features verificados por hash. O coletor leu apenas arquivos locais e não buscou dados nem regravou o cache compartilhado.
- SHA-256 do modelo `model.pkl`: `13c1b2dbd59a56d29ed172a5abb390159da0b6528989993b02641c1e7f9ad606`.
- SHA-256 de `model_training.json`: `55f315df0cb78b49b3b3d820eb43535938dce18112bc23caaaaa95064ad446dd`.
- Runner de ajuste congelado: `src/jev_trader/lowvol_hgb_freeze.py`; a tentativa inicial parou em `PermissionError WinError 5` ao criar um worker. O erro e a emenda de execução foram registrados em `research/EXPERIMENTS.jsonl`; a tentativa concluída usou um thread e os mesmos parâmetros.

Este artefato prova somente que um HGB foi ajustado sobre a amostra histórica pré-fixada. Não houve predição prospectiva, avaliação de EV, operação paper ou ordem real. A escolha histórica da família continua sujeita a viés de seleção; nenhuma estratégia foi aprovada. O modelo é CPU, não CUDA/GPU.
