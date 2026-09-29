# Validação das fontes da proposta após o Ciclo 12

Data da consulta: 28/09/2026  
Documento examinado: [Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md](Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md)

Esta validação cobre as referências externas e as afirmações técnicas associadas a elas. Não reproduz os resultados dos ciclos, não inspeciona os dados locais e não roda experimento ou backtest. “Confirmada” significa que a fonte sustenta a afirmação no limite descrito abaixo; não significa que uma estratégia tenha rentabilidade demonstrada.

## Alegações e vereditos

### 1. R² negativo e ordenação de oportunidades — seção 4

**Alegação:** R² negativo indica ajuste quadrático pior que uma previsão constante pela média na amostra; R² não mede diretamente a qualidade de ordenar oportunidades.  
**Veredito:** **Confirmada**, com a ressalva de que a segunda parte é uma leitura da definição da métrica.  
**Fonte direta:** [scikit-learn — r2_score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.r2_score.html). A documentação identifica R² como métrica de regressão, informa que pode ser negativo e que, para y_true não constante, prever sempre sua média produz R² igual a zero.  
**Limite:** isso compara erros quadráticos no conjunto avaliado; não prova capacidade de ordenação fora da amostra, retorno líquido, calibração financeira ou rentabilidade futura. Quando y_true é constante, a documentação registra valores não finitos e a substituição padrão de force_finite=True por 1 ou 0.

### 2. Learning-to-rank, grupos e score — seção 5

**Alegação:** XGBoost learning-to-rank requer grupos de consulta/candidatos; o score do ranker é de relevância/ordenação, não percentual de retorno, portanto não deve ser comparado diretamente a 0,012.  
**Veredito:** **Confirmada** quanto a grupos e natureza do score.  
**Fonte direta:** [XGBoost — Learning to Rank](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html). O tutorial organiza exemplos por qid, treina XGBRanker com esses grupos e descreve as saídas como relevance scores ordenados.  
**Limite:** a documentação não define quais candidatos financeiros devem compor cada grupo nem como criar rótulos úteis. Ela não converte scores em EV, não assegura calibração e não demonstra que o primeiro colocado tenha retorno esperado positivo. A observação da proposta de que escolher o melhor entre candidatos negativos não resolve o EV é uma consequência operacional plausível, não um resultado demonstrado pelo tutorial.

### 3. Campos de aggTrades — seção 7, “Informação incremental”

**Alegação:** arquivos oficiais de aggTrades incluem preço, quantidade, timestamp e indicação de se o comprador era maker.  
**Veredito:** **Confirmada**.  
**Fonte direta:** [Binance Public Data — repositório e formatos](https://github.com/binance/binance-public-data). O README lista, para Spot e USD-M/COIN-M, campos de trades agregados como preço, quantidade, timestamp e “Was the buyer the maker”; também identifica os endpoints de origem.  
**Limite:** o esquema documentado prova a presença desses campos, não a disponibilidade contínua de cada símbolo/período nem a completude dos arquivos. O indicador registra o papel maker do comprador; a interpretação de fluxo agressor, lado do taker e instante em que a feature estaria disponível precisa ser implementada e validada separadamente.

### 4. Unidade temporal em arquivos Spot — seção 7

**Alegação examinada:** a proposta chama o campo de timestamp, sem especificar a unidade.  
**Veredito:** **Imprecisa se isso for tratado como unidade uniforme**.  
**Fonte direta:** [Binance Public Data — nota sobre timestamps Spot](https://github.com/binance/binance-public-data). O README informa que timestamps de dados Spot a partir de 01/01/2025 são expressos em microssegundos; os exemplos de trades Spot mostram valores compatíveis com essa unidade.  
**Limite:** a nota citada é específica para Spot e para dados a partir dessa data. Ela não autoriza presumir a mesma unidade para todos os produtos, tipos de arquivo ou períodos. O parser deve usar o contrato correspondente ao arquivo/endpoint e verificar amostras; interpretar microssegundos como milissegundos desloca os horários em três ordens de grandeza.

### 5. Histórico de estatísticas de open interest — seção 7

**Alegação:** o endpoint documentado de histórico de open interest oferece somente o mês mais recente; por isso, a proposta recomenda auditar cobertura de arquivos oficiais antes de prometer histórico longo.  
**Veredito:** **Confirmada** para o limite do endpoint e para a cautela indicada.  
**Fonte direta:** [Binance USDⓈ-M — Open Interest Statistics](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#open-interest-statistics), endpoint /futures/data/openInterestHist. A documentação limita os dados disponíveis ao último mês e lista parâmetros de intervalo e máximo de 500 pontos por resposta.  
**Limite:** isso descreve esse endpoint de estatísticas USDⓈ-M; não prova que exista ou não exista arquivo histórico em outro produto oficial. O README geral de Public Data, por si só, tampouco prova cobertura histórica de open interest. Disponibilidade, período e integridade de qualquer arquivo candidato precisam ser verificados diretamente antes de uso.

### 6. Stream de liquidações — seção 7

**Alegação:** o stream é um snapshot; por símbolo, informa somente a liquidação mais recente no intervalo de 1000 ms, e a ausência de evento não representa um total igual a zero.  
**Veredito:** **Confirmada** quanto à regra do snapshot e ao intervalo.  
**Fonte direta:** [Binance USDⓈ-M — All Market Liquidation Order Streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market#all-market-liquidation-order-streams). A documentação diz que apenas a última ordem de liquidação por símbolo dentro de 1000 ms é enviada e que nenhum evento é enviado quando não ocorre liquidação naquele intervalo.  
**Limite:** isso caracteriza o comportamento desse stream, não um arquivo histórico nem uma contagem completa de todas as liquidações. O stream não deve ser tratado como volume total ou como confirmação exaustiva de eventos.

### 7. Binance Public Data, arquivos e checksums — seções 6 e 7

**Alegação:** há arquivos públicos diários/mensais e checksums para verificar integridade; a disponibilidade histórica deve ser auditada em vez de presumida.  
**Veredito:** **Confirmada**, com limite de cobertura.  
**Fonte direta:** [Binance Public Data — README oficial](https://github.com/binance/binance-public-data). O repositório descreve arquivos diários/mensais e arquivos .CHECKSUM; também registra que arquivos arquivados podem ser atualizados posteriormente.  
**Limite:** checksum verifica que o arquivo baixado corresponde ao checksum publicado naquele momento; não prova correção semântica, completude do histórico ou existência de qualquer combinação de símbolo, produto, período e granularidade. A frase “todos os símbolos são suportados” no README não garante que todo arquivo histórico pretendido exista.

### 8. Probability of Backtest Overfitting — referência 6

**Alegação examinada:** a referência é o artigo acadêmico The Probability of Backtest Overfitting, de Bailey, Borwein, López de Prado e Zhu, publicado no Journal of Computational Finance em 2017, sobre PBO e CSCV.  
**Veredito:** **Confirmada** como referência bibliográfica e fundamento geral sobre seleção/overfitting de backtests.  
**Fonte direta:** [registro acadêmico da UC e PDF do artigo](https://escholarship.org/uc/item/4w1110bb) ([PDF](https://escholarship.org/content/qt4w1110bb/qt4w1110bb.pdf)). O resumo propõe um arcabouço para estimar PBO e apresenta CSCV; o artigo define PBO em relação à configuração ótima in-sample que fica abaixo da mediana out-of-sample.  
**Limite:** a proposta não descreve uma implementação nem reporta estimativa de PBO/CSCV, então a citação não valida um cálculo no projeto. O artigo não demonstra rentabilidade da estratégia em análise e reconhece limitações do CSCV em problemas com informação estrutural. Não se deve ler a citação como aprovação de um método específico de validação temporal para estes dados.

## Alegações matemáticas sem sustentação nessas referências externas

O limite superior da média dos 200 maiores retornos (seção 3) é válido como dedução para retornos fixos, finitos, na mesma unidade e sem mudança de política/execução: nenhum subconjunto de pelo menos 200 elementos pode ter média superior à média dos 200 maiores. Essa demonstração não vem das fontes externas acima. Interações de carteira, impacto, custos não lineares ou alterações de saída invalidam a aplicação aos retornos fixos e estão corretamente apontados como limites na proposta.

A decomposição EV = p × G − (1 − p) × L (seção 5) é a identidade da esperança ao separar os casos r > 0 e r <= 0, desde que as probabilidades e médias condicionais usem a mesma definição de retorno e custos. Ela não valida a qualidade dos estimadores de p, G ou L, nem substitui replay líquido fora da amostra.

Os gates de EV acima de 1,2%, payoff, profit factor, tamanho de amostra, preferência de acerto perto de 70% e minimização de drawdown são critérios do projeto. Nenhuma das fontes citadas prova que sejam alcançáveis ou que alguma variante os satisfaça. Os resultados C06–C12 também não foram reproduzidos nesta verificação de fontes; permanecem reportados pela fonte interna indicada pela própria proposta.

## Nota de versão e reprodutibilidade

As URLs de scikit-learn e XGBoost usam o canal stable, que pode mudar. Para repetir a validação no futuro, fixe a versão da documentação ou arquive a página consultada junto do experimento. A consulta acima foi feita em 28/09/2026.
