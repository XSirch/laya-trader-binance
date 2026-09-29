# Protocolo: exposição Spot apenas durante a semana

## Hipótese e limites

Estudos anteriores sobre cripto encontraram resultados instáveis para o retorno por dia da semana e evidência mais consistente de menor volume e volatilidade durante o fim de semana. Uma regra fixa de caixa no fim de semana pode melhorar o retorno ajustado a risco se as 48 horas fora do mercado compensarem as altas perdidas e o custo dos giros. As fontes não mostram que esse mecanismo gere lucro direcional. O resumo crítico está em [calendar_strategy_sources_2026-09-27.md](calendar_strategy_sources_2026-09-27.md).

Esta regra é nova no inventário local, mas sazonalidade de calendário é uma família conhecida. O histórico Binance de janeiro de 2023 a agosto de 2026 já foi observado em outros experimentos; nenhum trecho será tratado como holdout intocado. O replay é retrospectivo e exploratório. Mesmo um resultado positivo exigiria confirmação paper prospectiva com cotações executáveis e tarifas reais.

## Regra congelada

- Universo fixo: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT Spot, sem posições vendidas ou alavancagem.
- Manter quatro contas isoladas com capital inicial igual a 25% cada. Cada conta reinveste somente o próprio saldo, sem rebalanceamento entre ativos.
- Comprar cada ativo na abertura de segunda-feira às 00:00 UTC usando todo o caixa daquela conta. Manter a posição até a abertura de sábado às 00:00 UTC, vender tudo e permanecer em caixa até a segunda-feira seguinte.
- Datas e horários são o único sinal. Cada execução usa o preço de abertura do candle horário que começa no limite UTC. Não negociar semanas sem ambos os limites e toda a sequência horária contínua; não interpolar lacunas.
- A janela termina no último sábado às 00:00 UTC com um ciclo completo. O benchmark usa os mesmos limites e os mesmos quatro pesos iniciais, compra uma vez na abertura inicial e mantém cada ativo até o limite final.
- Comparar custo de 0,15% e 0,25% por lado em toda compra e venda, inclusive a entrada e liquidação do benchmark. Taxas são hipóteses, sem spread, slippage, imposto ou juros sobre caixa. Não atribuir preço melhor que a abertura do candle.

## Dados e auditoria

Carregar exclusivamente os arquivos mensais Binance Spot 1h BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT de `data/binance/spot/1h`, verificando os SHA-256 do manifesto. Selecionar o primeiro limite semanal depois da última lacuna arquivada e exigir continuidade de uma hora para cada ativo até o limite final. Registrar arquivos, hashes, lacunas ignoradas, timestamps, ordens simuladas, quantidade e valor de cada fill, taxas, caixa e curvas por conta.

Reportar retorno acumulado e CAGR líquido, drawdown horário, limite adverso pelas mínimas horárias durante exposição, custos e turnover, proporção de semanas/meses positivos, resultados anuais completos e parciais, retorno bruto das 48 horas de fim de semana por ativo e comparação pareada com buy-and-hold. Ativos são correlacionados; quatro ativos não equivalem a quatro amostras independentes.

A regra é determinística e cada sinal depende somente do calendário. Não ajustar um modelo ML a cerca de 180 fins de semana nem buscar horários, ativos ou limiares após observar o replay. O ML já foi usado nos experimentos prévios de fluxos e ação de preço, ambos rejeitados; adicionar um modelo aqui ampliaria a seleção sem aumentar as observações de calendário independentes.

## Critério de decisão

A meta local permanece CAGR líquido de pelo menos 50% e drawdown máximo de 10% do capital total. Só considerar o gate atingido se ambos os custos satisfizerem os dois limites no período integral. Anos, meses, ativos, custos e curva adversa são diagnósticos obrigatórios; não selecionar o melhor subconjunto. Um resultado histórico favorável continua exploratório e apenas autoriza congelar uma versão para observação paper, nunca enviar ordens.

## Referências operacionais

- [Arquivos públicos Binance Spot e convenções de timestamp](https://github.com/binance/binance-public-data/blob/master/README.md).
- [Documentação oficial Binance para klines](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data).
