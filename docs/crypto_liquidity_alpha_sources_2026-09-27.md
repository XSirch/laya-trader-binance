# Revisão de fontes: liquidez agregada de stablecoins

Consulta em 27/09/2026. Escopo limitado à série usada como feature e à motivação para pesquisar liquidez cripto. Nenhum ativo além de pares cripto Spot entra na carteira.

## Fonte de dados

A documentação oficial da DeFiLlama lista `/stablecoincharts/all` como rota histórica para o market cap agregado de stablecoins. A resposta inspecionada contém `date` e `totalCirculatingUSD.peggedUSD`; esta pesquisa usa apenas esse campo de oferta em USD de tokens atrelados ao dólar. O endpoint público é `https://stablecoins.llama.fi/stablecoincharts/all`. A documentação descreve o conteúdo histórico, mas não promete snapshots históricos imutáveis nem horários de publicação para cada valor. A resposta deve ser preservada, hasheada e defasada; o uso retroativo ainda não prova disponibilidade ponto no tempo. [Documentação oficial de endpoints da DeFiLlama](https://github.com/DefiLlama/api-docs/blob/main/llms-pro.txt#L1794-L1829)

## Motivação e limite da literatura

- Um estudo de eventos de emissões de stablecoins encontrou retornos anormais positivos em torno de emissões na amostra de abril/2019 a março/2020, mas estudou eventos identificados por outra fonte e não valida uma previsão semanal contemporânea baseada em market cap agregado. [Ante et al., *The influence of stablecoin issuances on cryptocurrency markets*](https://www.sciencedirect.com/science/article/pii/S1544612320316810)
- Um artigo de 2026 estima connectedness entre retornos de BTC/ETH e mudanças de oferta de stablecoins e relata relações que variam por quantil/regime. A relação pode ser bidirecional; isso também permite que preço cripto antecipe emissão em vez de oferta antecipar retorno. Não é um teste de trading com custos. [Benedetti, Nikbakht e Pastén-Henríquez, *Quantile-based connectedness in the crypto-stablecoin network across market conditions*](https://www.sciencedirect.com/science/article/pii/S1059056026000250)
- Um trabalho sobre excesso de liquidez sustenta associação condicional entre liquidez e retornos cripto, mas fatores de risco, períodos e medidas são diferentes. Associação macro/financeira não estabelece alpha para esta carteira. [Nguyen et al., *Excess liquidity, cryptocurrency returns, and the moderating role of economic policy uncertainty*](https://eprints.whiterose.ac.uk/id/eprint/245239/)

Essas fontes justificam apenas uma hipótese distinta para ablação. Elas não fornecem parâmetros de entrada/saída, não demonstram consistência de 50% anual com drawdown máximo de 10% e não substituem a medição prospectiva de snapshots, fills, taxas e slippage.
