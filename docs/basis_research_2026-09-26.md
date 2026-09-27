# Resultado da convergência spot/perp

Foram concluídos 64 dos 64 cenários fixados; 0 ficaram inválidos. 0 atingiram nominalmente CAGR líquido de 50% com drawdown de até 10% e sem falha de margem. A meta permanece não demonstrada. Nenhum vencedor foi selecionado para operação real.

O [protocolo](basis_protocol_2026-09-26.md), as [fontes](basis_sources_2026-09-26.md) e o [congelamento](basis_freeze_2026-09-26.json) antecederam o primeiro cálculo financeiro. As duas referências foram comparadas com durações de 24/168 horas, frações spot de 50%/75%, dois custos e trailing ausente/4%. A comparação usa quantidades iguais de spot e short perp em BTC, ETH, BNB e SOL, com contas de caixa e margem separadas.

## Resultado observado

62 dos 64 cenários não fizeram nenhuma entrada. O maior CAGR posterior foi 0,0000%, em caixa; esse resultado não representa uma estratégia lucrativa. Entre os cenários que operaram, o maior CAGR foi **-0,0012%**, com drawdown observado de **0,0430%** e limite adverso intrahora de **1,4972%**. Configuração: `fundamental_r0; 24h; spot 50%; base; trailing None`. Esse máximo é descrição da grade, não seleção validada.

Na janela de janeiro de 2024 a 31/08/2026 às 23h UTC, o retorno acumulado foi -0,0031%, com uma entrada pareada e nenhuma observação de stress de margem. Atribuição sobre o capital inicial: convergência 0,0154 pontos percentuais, funding 0,0308 e custos 0,0493. CAGR inclui todo o tempo em caixa e a reserva de margem.

A mesma configuração em abril–dezembro de 2023 teve CAGR de 0,0000%, retorno acumulado de 0,0000% e drawdown de 0,0000%.

A operação foi em SOLUSDT: entrada em 29/02/2024 01h UTC e saída em 01/03/2024 01h UTC por duração máxima. O sinal projetava 0,3818% de convergência, contra 0,3805% de custo estimado: sobra de apenas 0,1360 ponto-base do notional spot. As versões com e sem trailing repetiram essa mesma operação; não são duas observações independentes. Uma única ocorrência não permite estimar consistência estatística.

Retornos por ano da configuração descrita (2026 é somente janeiro–agosto): 2024: -0,0031%; 2025: 0,0000%; 2026: 0,0000%.

No período posterior, 0 cenários tiveram CAGR positivo, 30 permaneceram sem entradas e 0 apresentaram stress de margem.

## Trailing e custos

Existem 16 comparações completas de trailing no período posterior. O trailing disparou 0 vezes somando esses cenários (operações sobrepostas entre cenários não são eventos independentes). Em 0 comparações reduziu o drawdown observado. A regra é observada de hora em hora e não garante uma perda máxima.

Dobrar custos também dobra o limiar de entrada. Por isso os cenários podem operar quantidades e datas diferentes; não se trata de aplicar duas tarifas à mesma sequência fixa de negócios.

## Grade completa

CAGR e drawdown em porcentagem. Os dois períodos reiniciam o capital. O limite intrahora e as demais séries estão no JSON.

| Referência | Horas | Spot | Custo | Trailing | CAGR 2023 | DD 2023 | CAGR posterior | DD posterior | Entradas posterior |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| fundamental_r0 | 24 | 50% | base | — | 0,0000 | 0,0000 | -0,0012 | 0,0430 | 1 |
| fundamental_r0 | 24 | 50% | base | 4% | 0,0000 | 0,0000 | -0,0012 | 0,0430 | 1 |
| fundamental_r0 | 24 | 50% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 24 | 50% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 24 | 75% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 24 | 75% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 24 | 75% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 24 | 75% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 50% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 50% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 50% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 50% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 75% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 75% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 75% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| fundamental_r0 | 168 | 75% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 50% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 50% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 50% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 50% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 75% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 75% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 75% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 24 | 75% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 50% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 50% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 50% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 50% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 75% | base | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 75% | base | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 75% | stress | — | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |
| median720 | 168 | 75% | stress | 4% | 0,0000 | 0,0000 | 0,0000 | 0,0000 | 0 |

## Evidência e limites

Passaram 494 testes da suíte completa (35,287 s, zero skips) e 14 novos testes do runner (0,023 s, zero skips). Uma revisão independente encontrou e corrigiu, antes do congelamento, insolvência escondida pelo spot, picos intrahora ausentes do limite de drawdown, liquidez sem volume, colisão de funding terminal e reserva para funding adverso.

A [verificação posterior](basis_verification_2026-09-26.json) registra o alcance e os limites da auditoria independente. Os [resultados estruturados](basis_research_2026-09-26.json) preservam todos os cenários, contagens e hashes; o arquivo completo está em `results/basis_research.json`.

A auditoria passou nos 64 cenários, verificando vinte arquivos congelados, os 712 ZIPs e os hashes dos contextos. Recalculou a contabilidade dos fills e pagamentos salvos sem chamar o simulador; o maior erro de reconciliação foi 2,22 × 10⁻¹⁶. A leitura dos CSVs foi independente, mas a reconstrução de indicadores reutilizou as fórmulas congeladas. O hash de todas as decisões de manutenção não foi refeito. Os arquivos escritos foram verificados como UTF-8 válido, sem caracteres de substituição.

O estudo usa 712 ZIPs e 122.780 estados, com todo o contexto técnico de ambas as pernas. A política decide por diferencial, funding, volume, ATR e volatilidade; médias, Fibonacci e outros campos do contexto não receberam uma alegação de benefício preditivo que não foi medida. Não houve nova chamada JEV, ordem ou download de mercado.

Os preços horários não comprovam execução simultânea de bid/ask. Tarifas, deslizamento, disponibilidade histórica do funding e regras de margem são hipóteses explícitas. O limite intrahora combina extremos possíveis e não é uma trajetória observada. A repetição de pesquisas no mesmo histórico impede tratar este resultado como confirmação intocada. Este teste pode rejeitar sua hipótese nas condições avaliadas; não demonstra inexistência de estratégias lucrativas em todos os mercados.

Commit de congelamento: `947d6e70d5b7bcb23f39d43c5c90f90234cf88a6`. Inputs SHA-256: `b4911b1041c53b65ad3b474524642b246e3e5e6f717bcfedc65a6aaef291cb8e`. Relatório completo SHA-256: `524571bf685ca7ad31fe595a375703de4c3f96609dc5b71a3a9df66ce1601ae4`.
