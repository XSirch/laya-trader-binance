# Convergência spot/perp com caixa e margem separados

Protocolo fixado antes de observar resultados desta hipótese. Meta: CAGR líquido anual de 50%, usando todo o capital, e drawdown máximo de 10%. Os arquivos históricos já foram usados em outras pesquisas: o período posterior não é confirmação intocada. As [fontes primárias](basis_sources_2026-09-26.md) e o [inventário](basis_data_inventory_2026-09-26.md) sustentam o mecanismo e delimitam o que os dados permitem verificar.

## Previsão e decisão

Comprar spot e vender perp em quantidades iguais nos quatro ativos BTC, ETH, BNB e SOL. Cada ativo tem um quarto do capital e nenhuma transferência entre ativos. A previsão é uma aproximação do diferencial a uma referência fixa durante a operação. Comparar duas referências: `fundamental_r0 = 1/1.0005 - 1`, inspirada no modelo com juros de caixa zero, e mediana dos 720 diferenciais horários anteriores, excluindo o atual. O hedge igual difere do hedge lambda da pesquisa original. Não há empréstimo, garantia de convergência ou investimento remunerado do caixa.

Definir diferencial `b = F/S - 1`. Projetar convergência `b - referência`. Exigir que exceda `2*custo_spot + 2*custo_perp*(1+b)` mais `max(-média_funding_passado,0)*ceil(horas_máximas/8)*(1+b)`. Créditos futuros não melhoram a previsão. Isso é uma aproximação de entrada: com quantidades iguais o ganho exato de preço por unidade de spot inicial é `b_entrada - b_saida*(S_saida/S_entrada)`; custos de saída também variam com o preço. A contabilidade usa os preços efetivos simulados de cada perna, sem transformar a projeção em lucro realizado.

Exigir volume cotado de pelo menos US$ 10 milhões nas últimas 24 horas em ambas as pernas e negócios positivos no último candle observado. Usar choque adverso `3*max(volatilidade20, ATR14)*sqrt(horas_máximas)`, em fração do preço. Rejeitar entrada se `(margem_inicial_conservadora - choque)/(1+choque) - reserva_funding < 0,20`, com margem inicial `(1-fração_spot)/fração_spot - custo_perp` e reserva `max(-média_funding_passado,0)*ceil(horas_máximas/8)`. A reserva debita o funding adverso projetado pelo notional após o choque. É um cenário de stress, não quantil probabilístico nem limite de perda. Sair quando o diferencial observado alcançar a referência fixada na entrada ou atingir a duração máxima. Não atualizar o alvo pelo resultado posterior.

O contexto preserva todos os campos de `market_state` para spot e perp: médias simples e exponenciais, suas distâncias e inclinação, ADX/DI, RSI, MACD, estocástico, retornos, ATR, volatilidade, Bollinger, drawdown, volumes, OBV, fluxo taker, VWAP, máximas/mínimas e Fibonacci de 60/180 barras. Neste estudo as barras são horárias, inclusive as chaves de retorno 7/30/90. Acrescentar distribuição do diferencial, mark e histórico de funding. Esses campos não são votos independentes: a política utiliza diretamente diferencial, funding, volume, ATR e volatilidade; os demais ficam disponíveis no contexto auditável. Não alegar benefício medido dos campos não usados. Livros sincronizados e uma série comum de posicionamento para os quatro ativos não estão disponíveis neste inventário.

Não chamar JEV nesta comparação. O contrato continua sendo uma única chamada com todos os parâmetros e critérios por ativo/instante, retornando aderência; o script decide. Nenhuma ordem ou gasto novo de API.

## Relógio e integridade

Para execução em `t`, o último candle abre em `t-2h` e termina em `t-1h`. A decisão espera uma hora completa após esse fechamento. Funding só entra no estado se seu timestamp for menor ou igual a `t-2h`: disponibilidade uma hora após o timestamp é hipótese, não evidência histórica de publicação. Exigir pelo menos 84 eventos em 30 dias passados, intervalo observado de oito horas, span mínimo de 27 dias e último evento há no máximo nove horas. Não olhar funding futuro para selecionar operação.

Reiniciar médias recursivas e janelas após lacunas; não preencher preços, volumes ou métricas ausentes. Exigir 721 candles consecutivos para diferencial atual e 720 anteriores. O buraco spot de março de 2023 exige novo aquecimento, com caixa durante a parte inicial de abril. Manter os candles de zero negócios. Se uma ordem simulada cair num candle sem volume e negócios positivos em qualquer perna, invalidar o cenário; a qualidade do candle de execução é checagem posterior, não preditor na abertura.

Verificar offline os três manifestos fixados e 712 ZIPs. Antes do replay, exigir sequência completa de preços das três séries durante os períodos de avaliação e calendário completo de funding nos slots 00/08/16. Ausência de pagamento não pode virar taxa zero. Isso valida os arquivos, sem escolher trajetórias pelo retorno. Preservar timestamps reais e desvios de milissegundos; o cache atual não comprova informação point-in-time.

## Carteira e execução

Cada bucket começa com fração spot 0,50 ou 0,75 e restante em margem. Só quando sem posição, transferir caixa realizado entre suas duas contas para restaurar essa divisão. Sem transferir lucro não realizado, usar spot como colateral ou redistribuir entre ativos. Quantidade `q = min(caixa_spot/[S*(1+custo_spot)], caixa_spot/F)`; a mesma quantidade abre as duas pernas. O short não credita o notional como dinheiro. Custos são debitados em cada uma das quatro execuções. Caixa negativo além da tolerância numérica invalida o cenário.

Custos por execução: base 0,12% spot e 0,07% perp; stress 0,24% e 0,14%. A base combina hipótese de taxa spot 0,10%, taxa perp 0,05% e deslizamento de 0,02% em cada perna. A taxa perp é cenário, sem verificação da tarifa da conta; páginas atuais não provam o histórico. O stress dobra cada custo e o limiar de entrada, portanto também pode mudar quais operações são feitas. Preenchimentos nas aberturas horárias são aproximações, sem bid/ask simultâneo, profundidade ou latência comprovados.

Funding positivo é crédito ao short. Na hora de entrada/saída, atribuir créditos à menor quantidade entre antes e depois, pelo mark mínimo da hora; débitos à maior quantidade, pelo mark máximo. Aplicar a mesma regra adversa ao slot da hora terminal, inclusive desvio de milissegundos posterior ao fechamento: débito possível, crédito zero após zeragem. É uma aproximação conservadora à incerteza do processamento, não fluxo reconstruído com timestamps de ordens. Funding real entra somente na contabilidade.

Patrimônio: caixa spot + inventário spot + caixa de margem + PnL não realizado do perp pelo mark. Fechar preventivamente ambas as pernas quando a margem observada for no máximo 20% do notional mark. Registrar falha se a margem cair abaixo de 10% no mark aberto ou alto intrahora. São heurísticas, sem reconstruir tiers oficiais de liquidação. Não usar patrimônio spot para esconder insolvência da conta futura.

Comparar ausência de trailing com trailing de carteira de 4%, observado nas aberturas. Ao disparar, fechar todos os pares e impedir reentrada naquela hora. O pico do trailing reinicia após zeragem; o pico global do drawdown não reinicia. A perda pode ultrapassar 4% entre observações ou ao executar. Reportar também limite adverso intrahora, incluindo pico favorável possível com spot alto/mark baixo e vale adverso spot baixo/mark alto; extremos podem não ser simultâneos. Este limite não é trajetória de preços observada.

Máximo de permanência 24 ou 168 horas. Não abrir operação cuja duração máxima ultrapasse o término da janela. Fechar tudo no final, incluindo custos e regra adversa de funding terminal. O último preço disponível é 31/08/2026 às 23h UTC, sem inventar abertura de setembro. Contabilizar por calendário completo, incluindo caixa parado.

## Comparação fixa e evidência

São 64 cenários: duas referências, dois horizontes, duas frações spot, dois custos, dois trailings e dois períodos. Não escolher parâmetros pelo desempenho. Separar desenvolvimento de abril a dezembro de 2023 e período posterior de janeiro de 2024 a agosto de 2026. Cada período reinicia capital e posições; histórico anterior pode alimentar indicadores. CAGR usa 365,25 dias. Mostrar retorno líquido, CAGR, drawdown, limite adverso, margem, convergência, funding, custos, entradas, saídas, meses e atribuição por ativo. Guardar decisões, transferências, carteiras e séries com hashes.

Mesmo um cenário histórico nominalmente acima da meta exige comparação de custos, estabilidade, execução verificável e confirmação futura. Não marcar a meta atingida só pelo melhor ponto desta grade. Congelar protocolo, código, testes, ambiente e hashes dos inputs antes de calcular retornos. Qualquer erro técnico deve preservar o artefato anterior e explicar a revisão; não ocultar cenários inválidos.

```json
{
  "schema_version": 1,
  "periods": {
    "development": ["2023-04-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
    "later": ["2024-01-01T00:00:00+00:00", "2026-08-31T23:00:00+00:00"]
  },
  "references": ["fundamental_r0", "median720"],
  "max_hold_hours": [24, 168],
  "spot_fractions": [0.5, 0.75],
  "portfolio_trailing": [null, 0.04],
  "costs": {"base": [0.0012, 0.0007], "stress": [0.0024, 0.0014]},
  "basis_history_hours": 720,
  "funding_publication_lag_hours": 1,
  "completed_close_execution_delay_hours": 1,
  "minimum_quote_volume24": 10000000,
  "margin_volatility_multiple": 3,
  "preventive_margin_ratio": 0.20,
  "stress_margin_ratio": 0.10,
  "target_net_cagr_pct": 50,
  "maximum_drawdown_pct": 10,
  "historical_point_in_time_verified": false
}
```
