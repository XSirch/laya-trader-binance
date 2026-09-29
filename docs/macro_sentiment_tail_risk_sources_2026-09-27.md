# Fontes: índice Fear & Greed para pesquisa de risco cripto

Consulta em 27/09/2026. Este arquivo registra as fontes que motivam o teste incremental de sentimento e os limites de uso dos dados.

## Dados e metodologia publicados pelo provedor

Alternative.me publica um valor diário de 0 a 100 para o mercado Bitcoin, uma API `GET /fng/` e um parâmetro `limit=0` que solicita todo o histórico disponível. O exemplo da API expõe o valor, a classificação e um timestamp Unix. O provedor exige atribuição junto a qualquer apresentação dos dados e permite uso comercial com essa atribuição. Sua página informa que o índice contém volatilidade (25%), momentum/volume (25%), redes sociais (15%), pesquisas (10%) e dominância (10%); pesquisas estão pausadas no texto consultado. A própria descrição ressalta que é um índice de Bitcoin, ainda que represente o sentimento mais amplo do mercado.

Fontes: [página do índice, metodologia e API](https://alternative.me/crypto/fear-and-greed-index/); [documentação oficial da API](https://alternative.me/crypto/api/).

Limite temporal: a API pública consultada não oferece snapshots históricos por data de publicação nem atesta que a série atual seja idêntica à originalmente exibida. O experimento usa atraso conservador de 48 horas em relação à decisão semanal, mas não consegue excluir revisões retroativas. Os resultados não devem ser tratados como uma simulação com vintages verificadas.

## Evidência empírica divergente

Zhou, Kang e Guo, “Predicting cryptocurrency returns for real-world investments: A daily updated and accessible predictor” (*Finance Research Letters*, 2023), relatam previsões fora da amostra com o índice para horizontes de um dia a uma semana. O estudo de 2026 “Do bitcoin returns move sentiment? Evidence from the crypto fear & greed index” relata que mudanças no índice não acrescentam ganho preditivo fora da amostra para retorno de Bitcoin no dia seguinte e que retornos precedem mudanças de sentimento. Esses resultados não são diretamente comparáveis: variam horizonte, período, especificação e alvo. A divergência justifica testar apenas valor incremental contra controle cripto e macro locais, com custos e regra de carteira.

Fontes: [artigo de 2023](https://www.sciencedirect.com/science/article/pii/S154461232300778X); [artigo de 2026, DOI 10.1016/j.finr.2026.100094](https://www.sciencedirect.com/science/article/pii/S305070062600006X).

## Por que adicionar ao modelo de cauda existente

O FGI combina preço recente, volatilidade e volume com sinais de redes sociais, dominância e buscas. Por isso, uma correlação com o risco semanal pode apenas duplicar inputs já presentes. O teste congelado é uma ablação de três features (nível, variação de 7 dias e de 30 dias) adicionadas aos controles idênticos. Uma queda do erro preditivo sem melhora líquida de carteira não será tratada como descoberta de uma estratégia lucrativa.
