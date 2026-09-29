# Binance MultiStrategy Research — v0.1

Núcleo Python de pesquisa, treinamento supervisionado, inferência e simulação para
**Binance Spot e futuros perpétuos USDⓈ-M**. Projeto criado em 27/09/2026.

## Situação desta entrega

**Código implementado e testado; não é um modelo financeiro já treinado e aprovado.**

- Há 8 estratégias candidatas, 54 variáveis de mercado e 66 entradas para o modelo.
- O treinamento produz um classificador de resultado líquido, um regressor de retorno em R
  e um calibrador de probabilidades. Existem artefatos separados para Spot e USD-M.
- Foram executados 52 testes de software, inclusive treinamento ponta a ponta em dados
  artificiais claramente identificados. Isso não é evidência de desempenho financeiro.
- Nenhum histórico real da Binance foi obtido nesta execução: houve falha de resolução
  de DNS. Não há pesos treinados em mercado real, resultado de backtest real, 70% de
  acerto comprovado, conexão com a conta, ordens reais nem custos de API de modelos.
- O pacote não altera o repositório `XSirch/laya-trader-binance`. Foi entregue separado
  para não sobrescrever as pesquisas Jev já existentes. Integração: `docs/HANDOFF_LOCAL.md`.

`docs/VALIDACAO_SOFTWARE.json` registra as verificações e limitações desta execução.

## A lógica do modelo

O sistema não compra simplesmente porque o RSI ficou abaixo de 30. Primeiro identifica
uma oportunidade numa das estratégias. Em seguida, o modelo supervisionado estima:

1. A probabilidade de o trade terminar com **lucro líquido positivo** depois de taxas,
   slippage e, em futuros, funding observado.
2. O retorno líquido esperado em unidades do risco inicial, chamado **R**.

As árvores de gradient boosting recebem o contexto, a direção, o regime e a identidade
da estratégia. Portanto, conseguem aprender interações específicas entre estratégia e
condições de mercado, sem precisar chamar Jev, Laya, OpenRouter ou outro LLM por decisão.
Não é uma rede neural fundacional nem um modelo de linguagem fine-tuned.

O regime inicial é uma regra explícita baseada no contexto de tendência de 15 minutos
 e 1 hora: alta, baixa ou indefinido/lateral. Um filtro separado evita volatilidade extrema.
O classificador aprende a filtrar candidatos dentro desses contextos; o regime em si
não é um detector de regimes treinado por HMM ou rede neural nesta versão.

**Observar cada minuto não significa executar a cada minuto.** Ausência de uma boa
combinação de oportunidade, probabilidade e retorno esperado produz `ABSTAIN`.

## Estratégias incluídas

Os parâmetros abaixo são hipóteses iniciais fixas para pesquisa, não configurações
com rentabilidade previamente comprovada. Long e short são espelhados em USD-M;
Spot só permite long e saída da posição comprada.

| Estratégia | Contexto/gatilho principal | Stop inicial | Alvo | Prazo máximo |
|---|---|---|---|---|
| `ema_pullback` | Retomada da EMA21 a favor da tendência | 2 ATR | 2 R | 240 min |
| `donchian_breakout` | Rompimento do canal anterior com volume/ADX | 2,5 ATR | 2,5 R | 480 min |
| `squeeze_breakout` | Compressão de Bollinger seguida de rompimento | 2 ATR | 2,5 R | 360 min |
| `range_reversion` | Extremo de Bollinger em mercado lateral | 1,5 ATR | 1,5 R | 120 min |
| `vwap_reclaim` | Recuperação/perda do VWAP a favor da tendência | 2 ATR | 2 R | 180 min |
| `fibonacci_pullback` | Retração 38,2%, 50% ou 61,8% com retomada | 2 ATR | 2 R | 360 min |
| `rsi_recovery` | Recuperação do RSI alinhada ao contexto | 1,75 ATR | 1,75 R | 180 min |
| `momentum_continuation` | Momentum, volume e MACD concordantes | 2,5 ATR | 2,5 R | 360 min |

Fibonacci usa extremos de uma janela **anterior** de 120 candles; não identifica swings
futuros nem usa ZigZag com repintura. O VWAP é móvel, calculado sobre 60 barras, e não
um VWAP de sessão de uma corretora. Essas definições são intencionais e auditáveis.

São calculados EMA9/21/50/200, RSI, ATR, ADX/DI, MACD, Bollinger, Donchian, VWAP,
volume relativo, desequilíbrio de compras agressoras quando disponível, retornos,
volatilidade e distâncias normalizadas. O contexto usa apenas candles **completos**
de 5m, 15m e 1h. Há aquecimento mínimo de 200 candles de 1h, ou aproximadamente 200h.

Não foram incluídos notícias, sentimento, open interest ou book histórico sem dados
verificáveis. Mais indicadores não substituem a comparação fora da amostra.

## Instalação no Windows com uv

Extraia o ZIP em uma pasta própria e abra o PowerShell nela:

```powershell
uv sync --extra dev
uv run pytest -q
uv run multitrader --help
```

Requer Python 3.11 ou superior. A execução de testes desta entrega usou Python 3.13.5;
as versões efetivamente usadas estão em `requirements-tested.txt` e no relatório de
validação. `uv sync`/download de dependências exigem acesso à internet.

O treinamento atual usa CPU. A RTX 4070 Ti não é obrigatória para esta arquitetura.
Não há treinamento CUDA neste pacote.

## Dados históricos reais

O comando público não solicita chave da Binance. Ele baixa ZIPs mensais oficiais,
verifica o SHA256 publicado e gera `candles.csv.gz` com um manifesto `dataset.json`.
Os intervalos abaixo são exemplos de **pesquisa exploratória**:

```powershell
uv run multitrader download --market spot --symbols BTCUSDT ETHUSDT --first-month 2023-04 --last-month 2026-08 --out data/spot
uv run multitrader audit --market spot --data data/spot

uv run multitrader download --market usd_m --symbols BTCUSDT ETHUSDT --first-month 2023-04 --last-month 2026-08 --out data/usd_m
uv run multitrader audit --market usd_m --data data/usd_m
```

Em futuros são baixados candles de negócio, candles de mark price e eventos de funding.
Ausência de arquivos, hash incorreto, gaps ou dados incompletos interrompem a ingestão;
a ferramenta não inventa candles nem substitui funding desconhecido por zero.
Os timestamps de Spot em microssegundos desde 2025 são normalizados por observação,
permitindo a transição de unidades entre arquivos anteriores e posteriores.

**Gaps reais:** a versão 0.1 exige uma série contínua de um minuto por ativo. Quando houver
um gap, tentar recuperar o trecho em arquivos oficiais diários ou selecionar um período
contínuo; não preencher preços artificialmente. Segmentação automática com reinício de
indicadores após interrupções ainda não está implementada. Símbolos recentemente listados
não podem ser avaliados antes de existir histórico suficiente.

### Dataset próprio

Para Spot, é aceito CSV/CSV.GZ com colunas:

```text
symbol,open_time,open,high,low,close,volume
```

`open_time` deve ser UTC em ISO 8601, segundos, milissegundos, microssegundos ou
nanossegundos. Opcional: `taker_buy_base`. Registros devem ser de 1m, completos e sem
duplicatas/gaps. Inclua o histórico anterior necessário para os indicadores.
Sem manifesto de origem, o arquivo será identificado como fornecido pelo usuário,
não como download da Binance verificado pela ferramenta.

Para USD-M, também são obrigatórios `mark_open,mark_high,mark_low,mark_close`,
`funding_rate` e `funding_event`, além de manifesto confirmando arquivos completos de
funding. Prefira o baixador. Não crie um manifesto dizendo que dados foram verificados
quando isso não aconteceu. Funding em `funding_rate` representa a liquidação daquele
minuto, não a taxa atual repetida em todos os minutos.

## Treinar modelos separados

Antes de rodar, edite as hipóteses de custo em `configs/spot.json` e `configs/usd_m.json`.
Os defaults são **suposições de pesquisa por lado**, não a sua tabela de taxas:
Spot: 10 bps de taxa + 5 bps de execução adversa; USD-M: 5 + 5 bps. O teste de estresse
duplica ambos. Um basis point, ou bp, equivale a 0,01 ponto percentual.

```powershell
uv run multitrader train --config configs/spot.json --data data/spot --train-end 2025-01-01 --calibration-end 2025-07-01 --selection-end 2026-01-01 --out models/spot_v01

uv run multitrader train --config configs/usd_m.json --data data/usd_m --train-end 2025-01-01 --calibration-end 2025-07-01 --selection-end 2026-01-01 --out models/usd_m_v01
```

As datas são fronteiras exclusivas, em UTC. Exemplo: treino até antes de 01/01/2025,
calibração até antes de 01/07/2025, seleção até antes de 01/01/2026. Há descarte de
janelas nas fronteiras e embargo de 480 minutos. Candles posteriores à seleção são
excluídos antes de gerar features de treinamento.

Não há divisão aleatória entre treino e teste. A subamostragem opcional, limitada a
250 mil linhas, acontece **apenas dentro do conjunto de treinamento**. Não muda a
separação cronológica. O early stopping aleatório dos estimadores está desativado.

O resultado é:

```text
models/spot_v01/
  model.joblib
  training_report.json
  environment.json
```

O relatório mostra classes, fronteiras de informação, custos, limiares testados,
resultado por estratégia/direção, benchmark das regras sem ML e status. Falha na meta
resulta em `target_not_demonstrated`, não em um resultado fabricado ou busca infinita
por um backtest bonito. O modelo é salvo para inspeção mesmo quando reprovado.

`joblib` usa serialização baseada em pickle: carregue apenas modelos gerados por este
código confiável. Não carregue arquivos de terceiros. O carregamento também exige a
mesma versão de scikit-learn e o mesmo fingerprint do código usados no treinamento.

## Testar sem voltar a ajustar o modelo

```powershell
uv run multitrader evaluate --model models/spot_v01/model.joblib --data data/spot --start 2026-01-01 --end 2026-09-01 --out results/spot_exploratorio

uv run multitrader evaluate --model models/usd_m_v01/model.joblib --data data/usd_m --start 2026-01-01 --end 2026-09-01 --out results/usd_m_exploratorio
```

**Essas datas não devem ser anunciadas como teste inédito:** as pesquisas prévias do
repositório já examinaram partes de 2025–2026. Use-as para diagnóstico exploratório.
Um teste realmente reservado precisa estar separado antes das escolhas e não pode
voltar a orientar ajustes. O seu próximo dataset pode cumprir esse papel desde que
não tenha sido examinado para desenvolver ou escolher esta versão.

Saídas: `evaluation.json`, `trades.csv`, `equity.csv`, `stress_trades.csv` e
`stress_equity.csv`. Um registro identifica reaproveitamento de janelas no mesmo
 diretório-pai. Ele não consegue provar que dados nunca foram vistos em outro lugar.

`walk-forward` aceita um JSON de folds explícitos, treina cada artefato apenas no
passado e recusa sobreposição entre as janelas de teste. Exemplo exploratório:

```powershell
uv run multitrader walk-forward --config configs/spot.json --data data/spot --folds configs/walk_forward.example.json --out results/walk_forward_spot
```

Os períodos de teste anteriores podem entrar no treino de um fold posterior quando
já são passado conhecido. Isso é walk-forward, não um motivo para reescrever os
resultados já registrados daqueles folds.

## Como a meta de 70% é avaliada

`win_rate` = trades encerrados com PnL líquido positivo / total de trades encerrados.
Não é accuracy de prever o próximo candle. Um trade com lucro bruto e prejuízo depois
dos custos conta como derrota. Nenhuma saída parcial multiplica artificialmente vitórias.

Os critérios iniciais de pesquisa são configuráveis, mas devem ser congelados antes
da avaliação: taxa observada >=70%; pelo menos 200 trades executados não sobrepostos;
8 semanas com operações; profit factor >=1,25; expectativa líquida positiva; drawdown
máximo <=15%; resultado positivo com custos estressados. Por padrão também se exige
que o limite inferior de um intervalo aproximado de 95%, por reamostragem de semanas,
seja >=70%. Portanto, observar exatamente 70% normalmente não basta para esse critério
mais exigente. O intervalo assume que blocos semanais sejam informativos; não elimina
mudanças de regime nem toda dependência temporal.

A busca é uma grade pequena e predefinida de limiares 0,70 a 0,95. Havendo mais de uma
configuração aprovada na seleção, é preferida a de maior número de trades. Isso ainda
é seleção de modelo: os números escolhidos não substituem um teste posterior inédito.
Probabilidade calibrada de 0,70 também não significa garantia de 70% de acerto futuro.

Se o sistema conseguir 80% de vitórias mas perdas raras eliminarem os ganhos, ele
reprova. Exemplo aritmético: 70 ganhos de 10 e 30 perdas de 30 resultam em -200 antes
de custos, apesar de 70% de acerto.

## Execução simulada e gestão de risco

O backtest entra na abertura posterior ao sinal. Uma posição global por modelo/mercado
é permitida, sem capital duplicado entre ativos. O tamanho usa risco inicial planejado
de 0,25% do patrimônio, com limite de 1x de exposição nocional e ajuste pelos custos.
Gaps podem causar perdas maiores que o risco planejado. Não há martingale.

O stop e o alvo são definidos a partir do preenchimento simulado, e não de um preço
médio inventado. Quando stop e alvo cabem no mesmo candle sem sequência conhecida,
o stop tem prioridade; gaps da abertura são tratados antes. O trailing nunca recua.
Ele é atualizado **após o fechamento de cada minuto**, para valer no minuto seguinte.
Isso evita usar a máxima de um candle para assumir um preenchimento que teria ocorrido
antes dessa máxima. Não é equivalente ao trailing percentual nativo da Binance.

O drawdown é medido nas marcações de fim de minuto e nas saídas executadas. Não é um
limite intraminuto. Nos futuros, o funding usa eventos históricos e um tratamento
conservador de minutos com ordem de entrada/saída/settlement desconhecida: débitos
podem ser considerados nos extremos, créditos ambíguos não são presumidos.

`PaperBroker`, em `paper.py`, é um motor orientado a eventos: reage a cada preço
recebido, trata stop/alvo sem esperar o minuto seguinte, atualiza o trailing no candle
fechado, deduplica sinais/funding e permite salvar/restaurar estado. Ele **não possui
transporte WebSocket, serviço contínuo ou conexão com conta Binance** nesta entrega.
O chamador precisa fornecer eventos ordenados de um transporte confiável.

Para inferência sobre o último candle do arquivo:

```powershell
uv run multitrader signal --model models/spot_v01/model.joblib --data data/spot
uv run multitrader signal --model models/spot_v01/model.joblib --data data/spot --diagnostic
```

São sinais offline, com indicação de dados antigos, modelo, estratégia, probabilidade,
retorno esperado e referências de stop/alvo. O modo diagnóstico pode mostrar candidatos
de um modelo reprovado, mas não libera ordens. Nunca use a referência de um arquivo
antigo como ordem atual.

## O que falta antes de operar dinheiro real

Treino e validação com históricos reais; avaliação realmente reservada; auditoria de
resultados por estratégia/regime; coletor contínuo; reconexão e recuperação de gaps;
reconciliação de ordens e posições; preenchimentos parciais; filtros de cada símbolo;
proteções nativas na corretora; testes de cancelamento, timeout e idempotência; teste
em ambiente de demonstração; limites consolidados se Spot e USD-M forem simultâneos.

USD-M nesta versão é uma simulação de long/short até 1x, sem modelo completo de margem,
liquidação ou ADL. Não habilitar alavancagem com este simulador. Testnet e paper não
provam liquidez, slippage ou rentabilidade de produção. Não envie chaves da corretora
no chat nem as coloque no repositório.

Veja `docs/PROTOCOL.md`, `docs/HANDOFF_LOCAL.md` e `docs/SOURCES.md`.
