# Sinais atuais e contabilidade em simulação

O candidato fixado agora pode gerar um estado atual reproduzível e avançar duas contas simuladas: referência e trailing de carteira de 4%. Cada conta começa com 10.000 USDT fictícios. A série `forward_paper_v2` preserva código, regra, dados de entrada e estado contábil por hashes. Nenhum dinheiro foi transferido e não há envio de ordens.

## Dados e decisões

O coletor conserva o histórico completo verificado para manter a inicialização de médias e suavizações. Atualiza candles diários fechados e funding por endpoints públicos. Os sessenta campos econômicos e técnicos são preservados para dezoito contratos ativos do universo original; EOS e MKR continuam registrados no histórico e indisponíveis para novas posições. Não há substituição retrospectiva de ativos.

O horário de corte respeita uma hora de disponibilidade após o fechamento diário. Candles em formação ficam fora do cálculo. A sobreposição com o histórico precisa coincidir; ausência de datas ou de um pacote completo de indicadores impede o sinal. Funding exatamente no corte diário não entra no sinal daquele fechamento. O script mantém todos os indicadores no contexto, mas a estratégia fixa continua usando sua fórmula declarada de baixa volatilidade e carry protegido; não há pretensão de que todos os campos recebam peso nessa fórmula.

O funding exige um predecessor conhecido e continuidade das ocorrências. Uma ampliação de intervalo exige verificação separada; o código não presume que uma ocorrência ausente seja uma mudança legítima de periodicidade. A integração também exige que um pagamento esperado já tenha sido retornado pela API antes de avançar o relógio contábil. Esse cuidado evita ignorar um pagamento que apareça com atraso.

## Contabilidade e horário

As posições são marcadas pelo ponto médio das ofertas observadas. Compras usam a oferta de venda e vendas usam a oferta de compra, com 0,05% de deslizamento adicional adverso e 0,10% de taxa. São premissas de simulação, não preços de execução confirmados. A quantidade disponível na melhor oferta deve cobrir a operação simulada; o código interrompe o avanço inteiro se qualquer perna não atender às verificações.

O funding observado incide apenas sobre quantidades que já existiam antes do tick. Preços, funding e taxas reconciliam o patrimônio a cada avanço. O trailing encerra todas as pernas e impede reentrada no mesmo tick. Uma nova máxima observada antes de custos de rebalanceamento permanece como referência do stop; custos não podem afrouxá-lo.

O comando aceita um tick horário entre os minutos 1 e 5, com limite superior exclusivo. O primeiro minuto é reservado à disponibilidade do funding. Rebalanceamentos ocorrem na janela de segunda-feira às 01:00 UTC; execuções simuladas usam as cotações realmente observadas nesse intervalo, não a abertura exata retrospectiva. Não há recuperação fictícia de decisões perdidas. Com posições abertas, uma lacuna superior a 65 minutos bloqueia o avanço contábil.

A primeira entrada elegível desta inicialização é **28/setembro/2026 às 01:00 UTC**, equivalente a **27/setembro às 22:00 em São Paulo**, sujeita à execução do comando dentro da janela e à validade dos dados. Até lá, a inicialização permanece em caixa. Uma inicialização anterior, também sem posições, foi preservada separadamente após a revisão de funding e do pico do stop; ela não é um histórico de rentabilidade.

## Execução e limites atuais

```powershell
.venv\Scripts\python.exe -m jev_trader.forward_paper --series forward_paper_v2
.venv\Scripts\python.exe scripts/snapshot_forward_paper.py
```

O primeiro comando coleta dados, avalia a agenda, registra um tick e termina. **Não há serviço contínuo ativo.** A preparação do acompanhamento não deve ser confundida com semanas de negociação simulada já realizadas. O relatório JSON distingue capturas, posições e operações simuladas; zero operações não comprova desempenho.

Uma tentativa real de retomada rejeitou a cotação de YFI por ultrapassar o limite de atualidade e não avançou a carteira. A observação rejeitada foi preservada; uma nova coleta pode tentar novamente sem alterar o limite. Isso demonstra a recusa de um dado inadequado, não disponibilidade operacional contínua.

Mudanças nos arquivos que definem a série bloqueiam sua continuação e exigem uma nova série explícita; uma execução repetida não apaga o histórico. A cadeia, os anexos de sinais e suas respostas brutas são verificados antes da continuação. Os hashes tornam alterações detectáveis quando comparados a uma referência externa, mas não certificam sozinhos a hora de aquisição.

As simulações ainda não modelam regras de liquidação, tributação, taxas específicas da conta ou restrições discretas de tamanho da corretora. Ordens simultâneas também são uma abstração; observar ofertas não garante preenchimento de toda a carteira. Nenhuma chamada adicional ao JEV foi necessária. Se ele for incorporado posteriormente, permanece restrito a pontuar aderência dos critérios com os indicadores reunidos em uma chamada por ativo/horário; o script mantém a decisão.

Evidência: `forward_paper_2026-09-26.json`. O objetivo de lucratividade consistente permanece sem confirmação prospectiva.
