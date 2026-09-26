# Fontes para convergência spot/perp

Consulta em 26/09/2026. Esta nota fundamenta um futuro teste com BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, sem calcular retornos locais, escolher limiares por desempenho, baixar séries de mercado ou chamar o JEV. A disponibilidade local está em [basis_data_inventory_2026-09-26.md](basis_data_inventory_2026-09-26.md). As páginas atuais da Binance não reconstruem automaticamente regras e tarifas vigentes em cada data histórica.

## Hipótese econômica

Comprar spot e vender o perp em quantidades iguais neutraliza a variação comum de preço, mas deixa o diferencial entre os mercados e o funding. Perpétuos não têm vencimento: o mecanismo de funding incentiva aproximação ao índice, sem uma data contratual que assegure convergência. Funding positivo transfere recursos de comprados para vendidos; negativo faz o inverso. O valor é calculado pelo notional no mark price. A Binance também informa desvio de até quinze segundos no processamento do pagamento; posições abertas junto ao horário podem participar. Usar eventos reais e uma regra explícita para colisões, sem transformar funding futuro em informação de entrada. [Binance, Introduction to Futures Funding Rates](https://www.binance.com/en/support/faq/detail/360033525031).

Para quantidade constante `q`, a identidade contábil antes de custos é `q * [(F_entrada - S_entrada) - (F_saida - S_saida)] + funding_recebido`, com preços efetivos das duas pernas. Trata-se de uma identidade, não de previsão. Um prêmio de entrada positivo pode desaparecer em custos ou ampliar antes do fechamento. O short futuro não disponibiliza o notional de uma venda spot: os fluxos pertencem ao contrato e à sua conta de margem.

A própria Binance oferece controles separados para spread de entrada e saída no bot de funding e avisa que o alinhamento das duas pernas pode levar tempo. Seu produto usa regras de conta específicas; não reproduzir sua alocação como se fosse prova de solvência para o nosso executor com carteiras separadas. [Binance, Funding Rate Arbitrage Bot, atualização de 07/04/2026](https://www.binance.com/en/support/faq/detail/f330e17d6fc04679b9b21d6f9350e787).

## Caixa, margem e execução

A Binance distingue saldo da carteira de margem: o primeiro incorpora transferências, lucro realizado, funding e comissões; o segundo acrescenta PnL não realizado, calculado no mark price. Portanto, reconhecer lucro no patrimônio não autoriza tratá-lo como caixa spot. [Binance, Futures Wallet Balance, atualização de 27/02/2026](https://www.binance.com/en-IN/support/faq/detail/5d62f8be18d24544b5b6156094c16bf7). Transferências entre spot e futuros são ações distintas e dependem do montante disponível. [Binance, Transfer Funds to the Futures Wallet, atualização de 14/01/2026](https://www.binance.com/en-IN/support/faq/detail/360033773532).

Recomendação contábil para o replay: representar caixa spot, inventário spot, caixa de margem, short, preço de entrada e PnL não realizado separadamente; debitar cada taxa na carteira correspondente; realizar PnL ao reduzir o short; permitir transferências apenas sob regra previamente definida e com caixa disponível. O patrimônio consolidado deve contar cada real de colateral uma única vez. Uma redução de risco precisa fechar ambas as pernas ou registrar explicitamente a exposição residual. Essa é uma proposta de implementação, não uma alegação de que todas as modalidades Binance tenham a mesma margem.

Os endpoints de mercado distinguem preço da última negociação de melhores bid/ask e suas quantidades. Candles contêm OHLC, volume e negócios; não contêm quatro cotações simultâneas dos dois mercados. Para entrada agressora, o diferencial relevante usa `bid_perp - ask_spot`; para saída, `bid_spot - ask_perp`, limitado pela profundidade e pela execução entre pernas. Inferência para o cache local: a diferença de fechamentos horários não comprova esse diferencial executável. [Binance Spot Market API](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market), [Binance USD-M Market Data API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

## Tarifas verificadas e hipótese de custos

| Mercado | Evidência consultada | Uso permitido no replay |
|---|---|---|
| Spot regular, sem desconto | Tabela atual mostra maker/taker de 0,100% / 0,100% | Referência pública atual de 0,10% por execução, sem provar histórico ou tarifa individual |
| USD-M regular, sem desconto | FAQ oficial usa 0,02% maker e 0,05% taker em exemplo; identifica as tarifas do exemplo como hipotéticas. A tabela atual consultada retornou `No records found` | 0,05% taker pode ser hipótese declarada; não está verificada aqui como tarifa atual da conta |

Fontes: [Binance Spot Trading Fee Rate](https://www.binance.com/en/fee/trading), [Binance Futures Fee Structure, atualização de 01/05/2026](https://www.binance.com/en/support/faq/detail/360033544231), [tabela USD-M consultada sem registros](https://www.binance.com/en/fee/futureFee).

Com essas hipóteses, comprar/vender spot e abrir/fechar perp custa aproximadamente 0,30% do notional de uma perna quando os preços são próximos, antes de spread/slippage. O cálculo exato deve aplicar a tarifa ao notional de cada uma das quatro execuções. Não dividir esse custo pelo notional bruto de duas pernas e depois compará-lo com o basis de uma perna. Fixar cenário base e stress de fee/slippage antes dos resultados; descontos, rebates e execução maker só com suporte próprio. Rentabilidade deve usar todo o capital alocado, inclusive reserva de margem e caixa parado.

## Pesquisa original e limites de transferência

[He, Manela, Ross e von Wachter, Fundamentals of Perpetual Futures, v7 de 17/09/2026](https://arxiv.org/html/2212.06888v7): amostra horária Binance até 11/03/2024. Seu custo alto usa maker de 0,0675% spot e 0,0144% perp; retornos são anualizados pelo tempo ativo. A teoria exige solvência da exchange, juros constantes, razão F/S limitada e função funding admissível. Compra `lambda` unidades spot para um short, não quantidades iguais. Isso impede transportar seus resultados para a carteira proposta.

Equações 7–12 e 17–19, com todas as taxas na mesma unidade temporal:

```text
p = (F-S)/F
Phi(p) = kappa*p + clamp(iota-kappa*p, -gamma, gamma)
D = kappa + sign(iota-r)*gamma - r              # r != iota
lambda = kappa/D
F_fundamental = lambda*S
rho = kappa*p + sign(iota-r)*gamma - r
c = 2*(fee_spot + fee_perp)                    # custo proporcional round trip
entrada_long_spot = rho > D*c                  # F-lambda*S > c*F
saida_no_benchmark = rho <= 0

r == iota:
F_inferior = kappa*S/(kappa+gamma-r)
F_superior = kappa*S/(kappa-gamma-r)
faixa_com_custo_C = [F_inferior-C, F_superior+C]
```

No caso regular, a faixa é `[lambda*S-C, lambda*S+C]`. `C` é custo monetário; na parametrização proporcional, `C=c*F`. O caso `r=iota` é um intervalo, não o ponto obtido por `sign(0)=0`. Fonte: equações citadas do mesmo artigo.

[Schmeling, Schrimpf e Todorov, Crypto Carry, BIS Working Paper 1087](https://www.bis.org/publications/working-paper-1087-crypto-carry.pdf), PDF consultado de 54 páginas, capa abril de 2023 e versão interna de 24/03/2023, especialmente seção 3.2: o estudo trata principalmente de futuros com vencimento, não autoriza transportar seu carry anualizado para perpétuos. Documenta limites de capital e o risco de liquidação do short enquanto o spot ganha valor em outra conta. Ausência de compensação de margens pode exigir recursos adicionais ou encerramento antes da convergência. Isso justifica acompanhar a solvência da carteira futura separadamente do drawdown consolidado.

## Mapeamento para os dados locais

| Variável ou requisito | Disponível no inventário local | Tratamento antes da implementação |
|---|---|---|
| `F`, `S` | Fechamentos horários negociados de perp e spot | Aproximação observável após ambos os fechamentos; não confundir com mark ou cotações simultâneas |
| `p=(F-S)/F` | Calculável causalmente dos fechamentos | Proxy do modelo; é diferente de `(F-S)/S` e do premium index operacional da Binance |
| `iota`, `gamma`, `kappa` | O inventário não reconstrói regras históricas por contrato | Para cenário de ciclo de oito horas, hipótese `iota=0.0001`, `gamma=0.0005`, `kappa=1`; converter também `r` para oito horas. Alternativamente anualizar todos por `3*365`, jamais só `r` |
| `r` | Sem série de juros de financiamento no inventário | Não substituir juros pela média do funding. Capital próprio sem empréstimo permite declarar `r=0` como custo de caixa assumido, não como estimativa da taxa livre de risco |
| Funding pago | Taxa, timestamp e intervalo dos eventos | Serve à contabilidade posterior e a sinais estritamente passados; não identifica o premium instantâneo nem o preço fundamental |
| Índice spot composto e impacto bid/ask | Ausentes | Não reconstruir a fórmula oficial de funding a partir de uma única cotação spot ou de OHLC |
| Clamp, caps, floors e mudanças históricas | Não catalogados como regras conhecidas em cada data | Uma função estática é cenário simplificado; funding efetivo deve vir dos eventos, sem substituição pela função teórica |
| Bid/ask, profundidade, latência e first-published-at | Ausentes | Executabilidade e disponibilidade histórica exata permanecem não comprovadas |
| Margem inicial/manutenção por tier e conta | Não reconstruída | Reserva e stress podem ser hipóteses do simulador, não reprodução de liquidação Binance |

A diferença operacional é verificável: a fórmula oficial usa índice composto, preços de impacto e média temporal do premium, seguidos por clamp e limites; o campo de funding histórico é o resultado agregado. Como o clamp tem um trecho plano, nem uma inversão algébrica do pagamento determina um único premium. [Binance, cálculo do funding](https://www.binance.com/en/support/faq/detail/360033525031).

Inferência para o desenho: com `r=0` e parâmetros de oito horas acima, `lambda=1/1.0005`, então o benchmark pressupõe perp ligeiramente abaixo do spot. Esse valor é consequência do cenário, não ajuste feito a retornos. É possível utilizá-lo como referência de sinal mantendo `q_spot=q_short`, desde que se declare a diferença para a carteira teórica. Replicar o modelo de financiamento, o hedge variável e suas bandas exigiria fontes adicionais; não é necessário fingir essa reprodução para testar honestamente uma hipótese inspirada nele.

## Consequência para o próximo protocolo

Fixar direção, atraso, custo mínimo de entrada, referência de saída, duração máxima e regra de caixa/margem antes de observar resultados. Usar somente candles fechados e funding já conhecido na decisão; execução posterior continua sendo aproximação na ausência de livros sincronizados. Registrar atribuição separada de convergência, funding e custos, além de horas com margem insuficiente e encerramentos forçados. Avaliar redução ou trailing sobre o resultado da posição pareada, com mecanismo executável nas duas pernas; OHLC não prova ordem intrabar nem garante perda máxima. Nenhuma fonte acima prova retorno líquido de 50% ao ano com drawdown de 10% nas condições locais.
