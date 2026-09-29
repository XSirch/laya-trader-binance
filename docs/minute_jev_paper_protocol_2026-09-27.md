# Protocolo: JEV com decisões Spot de um minuto

## Hipótese

O JEV recebe um snapshot de indicadores completos e escolhe uma ação tipada entre `BUY`, `SELL` e `IDLE` para BTCUSDT Spot. As séries de 1m, 5m, 15m e 1h incluem RSI14, MACD, médias, inclinação, ATR, Fibonacci, posição no candle, volume relativo, volume cotado e proporção agressora. O snapshot só usa candles fechados. É uma política distinta dos filtros JEV semanais já rejeitados: aqui a pergunta tipada retorna ação diretamente, uma vez por minuto.

## Lote e execução

- Observação prospectiva de papel por até 72 horas, limitada a 4.320 chamadas e US$ 1,00 de gasto reportado pela API.
- Um único mercado: Binance Spot BTCUSDT. Capital simulado de 100 USDT, apenas comprado ou em caixa; sem short, alavancagem, ativos fora de cripto ou ordens reais.
- Cada chamada ocorre depois do fechamento de um candle UTC de 1 minuto. O estado inclui a posição atual e os indicadores dos quatro timeframes.
- `BUY` abre posição se estiver em caixa; `SELL` fecha posição comprada; `IDLE` preserva o estado atual. Ações direcionais com probabilidade abaixo de 0,60 são tratadas como `IDLE`. `SELL` em caixa não abre short e `BUY` enquanto comprado não aumenta a exposição.
- A simulação usa o melhor ask para compra e bid para venda observados depois da resposta, mais 0,05% de slippage adverso e 0,10% de taxa por lado. A carteira é marcada no bid. Esses valores não substituem a tarifa real da conta nem garantem preenchimento.
- Falhas de rede, TLS, mercado, schema ou dados geram um minuto perdido, sem retry, ordem simulada ou chamada adicional naquele minuto. Respostas, estado, tempos, custo, cotações e conta ficam em ledger encadeado por hash.

## Gate de triagem após 72 horas

O gate só é avaliável com pelo menos 10 operações completas, ledger íntegro e ao menos 99% dos minutos programados com observação válida. Precisa ainda apresentar retorno líquido positivo após os custos simulados, drawdown observado menor ou igual a 5% e pelo menos duas das três janelas consecutivas de 24 horas, contadas desde o início, com PnL positivo. Se não houver operações ou falhar a qualidade de dados, o resultado é inconclusivo; se houver amostra suficiente e falhar o retorno ou risco, a hipótese é rejeitada.

Passar este gate apenas autoriza considerar uma janela paper maior. Três dias não estimam de modo confiável CAGR anual de 50%, drawdown máximo futuro de 10%, nem consistência entre regimes. O protocolo não declara a estratégia lucrativa, não instala negociação automática e não ativa ordens.

## Evidência e limites técnicos

O modelo fica congelado em `typesafe/jev-1.13`; os bytes das solicitações e respostas não incluem a chave da API. O custo local é interrompido em US$ 1,00 ou 4.320 chamadas, o que ocorrer primeiro. O endpoint Alpha é chamado apenas com validação TLS padrão; este protocolo não autoriza desativar verificação de certificados nem confiar em certificado de interceptação não instalado e validado pelo administrador.

O histórico recente é coletado do endpoint público Spot da Binance por HTTPS. Certificados, lacunas, atraso da resposta e spread podem impedir sinais. Uma chamada/minuto descreve o ritmo de decisão, não a frequência de trades. O resultado é um screening prospectivo de uma única moeda, não uma validação estatística abrangente.
