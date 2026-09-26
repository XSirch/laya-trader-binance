# Protocolo de pesquisa de funding e hedge

Definido em 26/09/2026, antes de calcular resultados desta família. Objetivo: testar se uma fonte de receita ligada ao funding tem maior persistência que as previsões direcionais já avaliadas.

Universo fixo: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. Fontes: arquivos oficiais Binance Spot, USD-M klines, markPriceKlines e fundingRate, com SHA256 e manifesto. Nenhuma ordem real ou empréstimo será feito.

Cada parcela compra quantidade `q` no spot e vende a mesma quantidade no perpétuo. A posição inicial por lado é limitada a 25% do patrimônio da parcela, mantendo o restante em dinheiro como colateral. Rebalanceamento semanal com exposição conhecida antes da abertura de execução. O simulador deve contabilizar marcação do futuro, variação da base, funding efetivamente observado, taxas nas duas pernas e saldo de margem. O total de valores nocionais das duas pernas no rebalanceamento é 50% do patrimônio; o nocional pode variar entre rebalanceamentos.

Comparações fixadas: carregar sempre; carregar somente com média de funding positiva nos 30 dias anteriores; exigir funding anualizado passado de pelo menos 8% para entrar e sair quando a média ficar negativa; exigir funding anualizado passado de pelo menos 15%. Não selecionar a moeda vencedora após ver o resultado. A seleção da regra usa desenvolvimento de 2024, e depois avalia separadamente 2025 H1, 2025 H2 e janeiro–julho/2026. Esses períodos já foram observados por outras famílias; a evidência é exploratória. Só depois de fixar a regra será aberto um período cronologicamente posterior para confirmação adicional.

Custos-base por lado: spot 0,15%, perpétuo 0,10%. Conservadores: spot 0,25%, perpétuo 0,15%. Stress adicional dobra esses custos. A diferença entre preço de marcação e preço negociado não pode ser confundida com lucro executável.

O funding de uma hora é aplicado somente à posição que já existia antes dessa hora. A entrada não pode ganhar o pagamento cujo valor ainda não era conhecido. Sinais utilizam eventos já publicados antes do instante de decisão. Valores reais de liquidação por faixa e execução com spread continuam exigindo validação própria; o teste usa um limite de margem conservador e deve sinalizar violações, sem ignorá-las.

Refinamento de execução durante a verificação: se rebalanceamento e liquidação de funding compartilham a hora, pagamentos positivos usam a menor quantidade entre antes e depois do rebalanceamento, e pagamentos negativos usam a maior. Isso evita ganhar por um evento cuja ordem exata dentro da hora não é demonstrada pelos candles. O funding no encerramento final da janela é excluído.

A frequência de entradas deixa de ser um substituto de amostra independente: nesta família, serão reportados pagamentos recebidos, dias expostos, meses positivos e estabilidade por janela, além de giros e drawdown. Uma posição longa em duração não pode ser aprovada simplesmente por coletar vários pagamentos altamente dependentes.
