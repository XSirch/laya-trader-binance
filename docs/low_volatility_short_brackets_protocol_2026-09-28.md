# Protocolo: saídas por stop/alvo no candidato short-only

## Objetivo

Testar uma hipótese de saída distinta para o candidato short-only: manter as entradas, universo, modelo e alocação congelados e fechar uma perna quando preço diário tocar um stop de perda ou alvo de lucro. A regra tenta limitar as perdas extremas que elevaram o drawdown combinado para mais de 10%.

Este teste não reutiliza como novidade o estudo anterior de barreiras em BTCUSDT Spot: aquele era long-only, em barras horárias e com horizonte máximo de oito horas. Aqui as entradas são shorts multiativos de futuros USDⓈ-M, calculados semanalmente, com barreiras em barras diárias.

## Entradas congeladas

- Regra-base: `low_volatility30_betahedged`, mas abrir apenas as pernas short aceitas pelo HGB regressor do protocolo short-only.
- Modelo, features, histórico móvel de 104 semanas, mínimo de 100 episódios de treino e limiar previsto de EV `>=1,2%` do notional permanecem idênticos ao estudo-base.
- Treino usa somente episódios de referência encerrados antes da decisão; as decisões de entrada são semanais às segundas-feiras, no open diário usado pelo replay original.
- Só posições short; o notional bruto total permanece 25% do patrimônio, dividido igualmente entre posições aceitas, sem alavancagem.
- Quando uma barreira fechar uma posição, ela não reabre no mesmo dia. Pode abrir novamente na próxima rebalanceada semanal se o sinal congelado ainda selecionar o par.
- Sem barreira tocada, saída e redimensionamento continuam seguindo o sinal original. A barreira fica ancorada ao preço da primeira entrada do episódio e não é movida quando a posição é redimensionada.

## Saídas e execução

Grade congelada antes do replay:

- stop adverso de 4%, 6%, 8% ou 10% do preço de entrada;
- alvo favorável de 1,2R ou 1,5R, onde R é a distância do stop; os alvos, portanto, são 4,8%–15% do preço de entrada.
- controle adicional sem barreiras para reconciliar o motor com os resultados anteriores.

Os dados disponíveis são OHLC diários. Na abertura do dia, primeiro se marca o PnL até o open e verifica-se se uma posição herdada abriu além de uma barreira; se sim, ela fecha ao open e fica impedida de reentrada até a próxima decisão semanal. Depois ocorre o rebalanceamento semanal das demais pernas, preservando a âncora da barreira de cada episódio; em seguida são avaliadas as máximas e mínimas do candle. Se stop e alvo forem tocados no mesmo candle, presume-se stop primeiro. Um alvo intraday executa exatamente no limite, sem melhoria; gaps favoráveis executam ao open. Um stop executa no limite, exceto quando há gap adverso, caso em que executa ao open. O fechamento terminal segue o open final do motor-base e não consulta o OHLC posterior.

Como o horário intradiário dos toques não pode ser reconstruído, em dia com barreira tocada o estresse de funding inclui os pagamentos adversos observados daquele dia e não credita recebimentos positivos posteriores à abertura; eventos na abertura conservam a escolha de quantidade antiga do motor-base. A fricção executada agrega taxa e slippage adverso sobre o notional negociado em cada entrada, saída ou redimensionamento: 0,10% por lado no cenário-base e 0,20% por lado no estresse dobrado vigente para USD-M (5 bps de cada componente na base). Para auditar o estudo de origem, o controle sem barreiras também reproduz seus custos originais de 0,10%/0,15%; esse stress de 0,15% não substitui o gate atual de 2x. O drawdown marcado usa o fechamento diário de posições remanescentes. O limite adverso diário marca simultaneamente todas as posições short abertas na máxima OHLC, mesmo que uma barreira também tenha sido tocada; é um limite conservador e não uma trajetória realizada. Nenhuma dessas medidas reconstrói fills reais.

## Avaliação

Reutilizar somente as decisões semanais já gravadas em `results/low_volatility_short_only_20260928.json`: validação 2024, calibração H1/2025, validação H2/2025, confirmação jan–jul/2026 e combinado. Reconstruir os alvos a partir dos estados arquivados e das previsões salvas, sem retreinar o HGB; conferir que quantidade e nomes de pernas aceitas em cada segunda-feira sejam compatíveis com o controle, e comparar o ledger completo de episódios por símbolo, datas, preços, taxas, funding e PnL. O desenvolvimento 2022–2023 não tem previsões semanais persistidas nesse resultado e fica fora, para não repetir o treino. Antes do grid, executar o controle sem barreiras e exigir reconciliação exata com o ledger short-only já publicado nos custos 0,10%/0,15%; acrescentar o controle no stress vigente de 0,20% para comparação com as variantes. Informar por cenário e por custo: operações fechadas, semanas UTC com exposição, acerto, payoff líquido, profit factor, EV líquido por operação sobre notional inicial, retorno da carteira, funding, drawdown marcado e limite adverso diário.

Aplicam-se os critérios vigentes do projeto, que substituem os gates antigos deste protocolo: EV líquido-base estritamente `>1,2%`, payoff-base `>=1:1`, profit factor-base `>=1,25`, pelo menos 200 operações completas e não duplicadas em pelo menos oito semanas ativas por variante e mercado, e PnL líquido agregado positivo sob taxas e slippage dobrados, mantendo funding observado. A taxa de acerto próxima a 70% é preferência, não gate. Não há teto numérico de drawdown; reportar as medidas marcada e adversa e minimizá-las entre candidatos que cumpram os outros gates.

Os períodos e a direção short já foram examinados. Resultados por janela e o período combinado são diagnósticos retrospectivos: não somar folds, mercados, cenários ou variantes para chegar a 200, e não declarar aprovação histórica independente. O grid não seleciona um vencedor; qualquer resultado serve para rejeitar ou gerar uma hipótese para avaliação prospectiva congelada, nunca para autorizar ordens reais.

Este motor não simula margem de manutenção, liquidação, proteção de preço da corretora nem os parâmetros de margem da conta do usuário. Os resultados USD-M são replays de PnL sob exposição simulada e não demonstram que o sizing sobreviveria às regras de margem ou execução da conta.

## Integridade

Não modificar a regra-base, threshold, features, universo, períodos nem custos após observar os resultados. Preservar o relatório/protocolo anterior e seus ledgers. Nenhuma chamada JEV, ordem real ou alteração no observer minuto a minuto.
