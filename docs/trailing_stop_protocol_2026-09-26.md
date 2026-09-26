# Trailing stop: protocolo antes da comparação

Solicitado pelo usuário para avaliar redução de perdas. Não será presumido que um trailing stop garante saída no preço indicado nem elimina prejuízo.

Comparar inicialmente na combinação de baixa volatilidade e carry com hedge de beta já fixada: sem stop; trailing por posição de 2%, 4% e 8%; trailing por posição de 2 e 3 ATRs diários de 14 períodos; e trailing da carteira de 2%, 4% e 8%. Essa base evita escolher um novo previsor pelo desempenho posterior.

Para posições, o stop usa somente máximos/mínimos favoráveis de horas já encerradas. A máxima da hora atual não pode apertar retroativamente um stop atingido na mesma hora. Gaps são executados na abertura observada, mesmo se pior que o stop. Um toque intrahorário usa o nível do stop com os custos por lado já definidos; essa hipótese de execução não comprova liquidez real em movimentos bruscos. O ATR será calculado apenas com candles diários completos disponíveis antes da hora avaliada. O nível só pode apertar, nunca afrouxar; reduzir ou aumentar uma posição no mesmo sentido não apaga seu histórico favorável.

Para a carteira, monitorar o patrimônio nas aberturas horárias observadas e encerrar todas as pernas quando ultrapassar a distância percentual do máximo do ciclo. Não reconstruir um patrimônio intrahorário usando extremos de ativos que podem ter ocorrido em momentos diferentes. Após stop, a reentrada só pode ocorrer no próximo rebalanceamento semanal; não reabrir no mesmo horário do encerramento. Um novo ciclo reinicia o máximo da carteira.

Comparar retorno líquido, queda máxima, meses positivos, custos, frequência de stops, tempo em caixa e exposição líquida após encerrar pernas individuais. Manter os custos de 0,10%, 0,15% e 0,30% por lado. Reportar separadamente 2024, 2025, janeiro–julho/2026 e agosto–setembro/2026. Todos são períodos retrospectivos já vistos; nenhum stop será declarado vencedor independente apenas pelo melhor agregado posterior.

A decisão continua no script. O JEV não envia ordens nem escolhe stops. Não há autorização de operação real.
