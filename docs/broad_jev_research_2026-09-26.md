# Replay JEV com todos os campos diários da carteira de futuros

**Nenhum dos 40 cenários atingiu simultaneamente CAGR de 50% e drawdown de até 10%.** Foram concluídas 2.785 chamadas, cada uma com os sessenta campos de mercado e as cinco perguntas de aderência no mesmo corpo. O JEV devolveu pontuações; o script aplicou os critérios e decidiu a exposição. Neste experimento, as pontuações recebidas não fizeram o script aprovar nenhuma semana. A carteira JEV permaneceu em caixa nos dois períodos, sem retorno de negociação.

O protocolo e a preparação foram registrados no commit local `8f218ff` antes da aquisição paga. Todas as respostas estão completas, os quarenta replays terminaram e os hashes de código, protocolo e entradas permaneceram iguais. A carteira original reproduziu exatamente os quatro cenários previamente registrados no período combinado, incluindo retorno, drawdown, taxas e registros de fechamento por stop.

## Comparação econômica

O período combinado vai de 1/janeiro/2024 a 26/setembro/2026, com 999 dias e 143 decisões semanais. CAGR é o retorno anual composto; os valores não são o retorno acumulado do período. Cada célula abaixo contém **CAGR / drawdown máximo horário**, em porcentagem. Custos incluem a hipótese de negociação por lado e o funding observado; não incluem impostos ou despesa de pesquisa com API.

| Política fixa | Custo de 0,15% por lado | Custo de 0,30% por lado | Semanas com alvo não nulo |
|---|---:|---:|---:|
| Referência, sem trailing | 9,80% / 12,49% | 7,92% / 12,69% | 143 |
| Referência, trailing de carteira de 4% | 12,36% / 7,43% | 9,12% / 10,33% | 143 |
| Numérico, escala 1, sem trailing | 0,23% / 1,97% | 0,04% / 2,21% | 4 |
| Numérico, escala 1, trailing de 4% | 0,23% / 1,97% | 0,04% / 2,21% | 4 |
| Numérico, escala 4, sem trailing | 0,85% / 7,57% | 0,11% / 8,50% | 4 |
| Numérico, escala 4, trailing de 4% | 0,12% / 8,72% | −0,62% / 9,64% | 4 |
| JEV, escala 1, sem trailing | 0,00% / 0,00% | 0,00% / 0,00% | 0 |
| JEV, escala 1, trailing de 4% | 0,00% / 0,00% | 0,00% / 0,00% | 0 |
| JEV, escala 4, sem trailing | 0,00% / 0,00% | 0,00% / 0,00% | 0 |
| JEV, escala 4, trailing de 4% | 0,00% / 0,00% | 0,00% / 0,00% | 0 |

Escala 1 limita o alvo bruto a 50% do patrimônio; escala 4 amplia uniformemente a cesta para alvo bruto de até 200%, somente em simulação. O filtro preserva as proporções da carteira, inclusive o hedge. A contagem de semanas com alvo não nulo não mede duração da exposição nem número de ordens.

Em desenvolvimento, 2022–2023, os dois filtros também ficaram inteiramente em caixa. A referência sem trailing teve CAGR de 9,75% e drawdown de 10,56% a 0,15% por lado; com trailing, 7,74% e 10,10%. A custo dobrado, os pares foram 7,95% / 10,90% e 6,51% / 10,06%. Cada período começou com sua própria carteira em caixa; não são uma trajetória única de 2022 a 2026.

O trailing melhorou a referência no trecho combinado, mas não em todos os períodos e combinações. Na escala 4 do filtro numérico, reduziu o CAGR de 0,85% para 0,12% e elevou o drawdown observado de 7,57% para 8,72%. Houve dois acionamentos de carteira, que geraram dezenove registros de fechamento de posições. Na referência com custo de 0,15%, foram dez acionamentos e 104 registros de fechamento. Não confundir o campo `stop_count`, que conta posições encerradas, com acionamentos distintos da carteira.

O limite adverso intrahorário da referência com trailing foi 7,91% a 0,15% e 10,42% a 0,30%. No filtro numérico escala 4 com trailing, foi 9,40% e 10,32%, respectivamente. Nenhum cenário passou a meta também sob esse limite; não houve sinalização da heurística de margem. Essa heurística não prova ausência de liquidação em conta real. O trailing é observado por hora, sujeito a custos e à trajetória de preços, e não impõe um teto garantido à perda.

## Aderência e decisões do script

O script exige risco de pelo menos 0,75 e pelo menos dois dos quatro apoios de pelo menos 0,65. A cesta só recebe exposição quando os ativos que passam representam pelo menos 60% de seu peso bruto original. O comparador numérico usa exatamente os mesmos números arredondados enviados ao modelo.

| Critério | Divergências entre JEV e regra exata no limiar 0,50 | Total de avaliações |
|---|---:|---:|
| Tendência | 193 | 2.785 |
| Timing | 636 | 2.785 |
| Participação | 158 | 2.785 |
| Estrutura | 767 | 2.785 |
| Risco | 213 | 2.785 |

O limiar 0,50 desta tabela serve ao diagnóstico binário, não é o limiar de entrada. Aplicando os limiares reais do script, houve 337 divergências de aprovação por ativo entre JEV e cálculo exato. Isso não corresponde a 337 operações: a decisão final ainda depende da fração de peso aprovada na semana. As pontuações não foram calibradas como probabilidade de lucro.

A aprovação completa por ativo caiu de 482 avaliações numéricas para 161 com JEV: 329 aprovações numéricas foram recusadas, e houve oito aprovações adicionais. A fração semanal máxima com JEV foi 49,33% no período combinado e 29,24% em desenvolvimento, sempre abaixo dos 60% exigidos. Nas quatro semanas aprovadas pelo cálculo exato, as frações JEV foram 29,56%, 27,97%, 37,44% e 29,30%, respectivamente. A permanência em caixa decorre desses números e da regra local, sem respostas ausentes ou falha de execução.

As divergências não caracterizam simplesmente maior conservadorismo: no critério de estrutura houve 759 falsos positivos e oito falsos negativos no limiar diagnóstico de 0,50. Nos limiares reais do script, tendência passou em 1.425 estados numéricos e 565 estados JEV; timing, em 1.880 e 1.040; estrutura, em 374 e 825. Os dados mostram que as pontuações não representam de forma confiável estes critérios booleanos nos limiares fixados. A auditoria não observa nem presume o raciocínio interno do modelo.

O [diagnóstico numérico separado](broad_jev_numeric_diagnostics_2026-09-26.md) mostra por que o próprio filtro exato foi tão restritivo: ATR e volatilidade bloquearam muitas posições vendidas; carry desfavorável bloqueou parte das compradas; a participação por volume foi pouco frequente nas observações dominicais. A análise descreve os estados fixados. Não houve mudança de limiares, calendário, escala ou critérios depois de observar os resultados.

## Gasto e execução das chamadas

| Item | Valor |
|---|---:|
| Replay multimetric spot anterior, 332 chamadas | US$ 0,043515150 |
| Novo replay broad, 2.785 chamadas | US$ 0,404491164 |
| Gasto acumulado dos dois ledgers | **US$ 0,448006314** |
| Teto cumulativo autorizado | US$ 2,000000000 |
| Saldo aritmético da autorização | US$ 1,551993686 |

Não há reserva pendente ao terminar. A auditoria independente conferiu 5.570 linhas na cadeia: 2.785 reservas e 2.785 conclusões, com identificadores únicos de requisição. Os corpos reconstruídos têm de 9.262 a 9.335 bytes; o uso registrado varia de 3.415 a 3.491 tokens de entrada. Cada cobrança coincide exatamente com esse uso ao preço de US$ 0,042 por milhão de tokens.

O modelo retornado foi `typesafe/jev-1.13-20260917`. A latência por chamada teve mediana de 0,580 s, percentil 95 de 0,740 s e máximo de 2,122 s, incluindo rede e provedor, com até quatro solicitações distintas concorrentes. São medições desta execução, não garantia futura de tempo de resposta. Todos os indicadores e todas as perguntas de um mesmo ativo/instante foram enviados juntos.

O cliente contabiliza o ledger anterior e o novo com `Decimal`, reserva antes do POST, impede repetição automática de pedidos incompletos e mantém o bloqueio de gasto quando uma reserva não resolvida é reaberta. Os custos são despesa de pesquisa apresentada separadamente; o zero de retorno das carteiras JEV não significa custo total zero para o projeto.

## Evidência e reprodução

| Artefato | SHA-256 |
|---|---|
| Eventos imutáveis, `results/broad_jev_events.jsonl` | `d8986609ff675bf6e211b74c47974c728a5804886af653ba31b696d97397cb1d` |
| Manifesto de entradas, `results/broad_jev_inputs.json` | `e6a7ac2efbd58bcbc5bd34273ab3b4f47f57dd08cccaad0b07254cf5f11d4438` |
| Respostas e cobranças, `results/jev_broad_decisions.jsonl` | `fecd5159fae2367401dd68e5e609da763bda9e28f927be0ca556fa8169839b6a` |
| Relatório completo, `results/broad_jev_research.json` | `3a5d19be3cb27d79166c41d7189499b844e70177f7f2a0afb6792c8078716ee9` |

O [JSON resumido versionado](broad_jev_research_2026-09-26.json) preserva métricas, fontes e hashes; o relatório completo local inclui trajetórias, auditoria de execução e eventos de stop. O [protocolo](broad_jev_protocol_2026-09-26.md) e a [preparação anterior à API](broad_jev_prepare_2026-09-26.json) permitem distinguir critérios fixados de resultados observados. A preparação validou 4.182 fontes diárias, 1.283 horárias, 1.045 horárias de desenvolvimento e 54 snapshots REST previamente armazenados, sem nova aquisição de mercado pela rede.

Para recalcular a partir do cache, sem novas chamadas pagas:

```powershell
.venv\Scripts\python.exe -m jev_trader.broad_jev_research
```

Esse comando regrava os relatórios e seu horário de criação, portanto o hash de saída muda. Estados, respostas, protocolo e código devem manter os hashes fixados. Os testes de política, causalidade, integração e orçamento integram a suíte local de 180 testes aprovados antes da aquisição.

Os períodos já foram examinados em outras pesquisas. Omitir símbolo e calendário do estado enviado não exclui conhecimento histórico no treinamento do modelo. Este resultado não identifica uma estratégia que satisfaça 50%/10%, não comprova que tal estratégia seja impossível e não justifica promover este filtro. O experimento não alterou a estratégia paper em execução nem enviou ordens reais.
