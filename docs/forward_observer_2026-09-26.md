# Aquisição atual para observação futura

O histórico já foi examinado em muitas hipóteses. Para produzir evidência nova, foi implementada e executada a primeira etapa de observação: capturar respostas públicas atuais, verificar sua atualidade e preservar uma sequência auditável. Essa etapa não é um simulador completo e não comprova retorno futuro.

O comando `python -m jev_trader.forward_observer` consulta somente GETs públicos de horário, informações dos contratos e melhores ofertas de compra/venda. Não lê credenciais nem possui rota de envio de ordens. Cada captura preserva os bytes recebidos, URL, horários locais, hash SHA-256, condições dos contratos e idade das ofertas. A idade máxima admitida é de 30 segundos. Ofertas cruzadas, valores não finitos, quantidades não positivas e horários futuros são rejeitados.

As capturas são encadeadas por hash e horário crescente. Antes de acrescentar uma observação, o comando verifica a cadeia e os arquivos brutos anteriores. Um bloqueio exclusivo evita gravadores simultâneos. A evidência versionada serve como referência externa para detectar alterações posteriores; hashes locais não equivalem a um serviço independente de certificação temporal.

A coleta real encontrou dezoito contratos negociáveis do universo original. EOSUSDT estava ausente e MKRUSDT estava com status `SETTLING`; eles foram registrados como indisponíveis, sem apagar sua participação no histórico. Todas as dezoito cotações passaram nas verificações de atualidade e integridade dessa coleta.

Ainda faltam integrar atualização causal dos sessenta indicadores, agenda de decisões, contabilidade de posições simuladas e funding, saídas por trailing, custos e tratamento explícito de interrupções. O comando executa uma captura e termina. Não há serviço contínuo ativo, carteira em execução ou retorno prospectivo a reportar. Não contar capturas avulsas como se fossem monitoramento contínuo.

O artefato `forward_observer_2026-09-26.json` ancora as observações disponíveis. Os bytes completos permanecem em `results/forward_observer/raw`, e o livro local em `results/forward_observer/observations.jsonl`. Executar `python scripts/snapshot_forward_observer.py` após novas capturas para atualizar a evidência versionada. Nenhuma chamada adicional ao JEV foi feita.

As consultas seguem a [documentação oficial de dados de mercado da Binance](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data). O melhor preço disponível é uma observação do livro, não prova de preenchimento de uma ordem ou de execução simultânea de toda a carteira.
