# Resultado: varredura e reclaim intraminuto

## Decisão

Sem modelo ajustado e sem candidata. A regra encontrou 45 eventos brutos em todo o período: seis em BTC, 11 em ETH, sete em BNB e 21 em SOL. Após separar cronologicamente e decluster o treino por 60 minutos, restaram 15 casos de treino, muito abaixo do mínimo de 400. Não relaxei o risco mínimo de stop depois de ver a amostra.

## Resultado do gatilho fixo

Os 24 eventos de validação resultaram em 22 operações após a regra de posição única/cooldown. A confirmação de janeiro–agosto/2026 contém apenas seis eventos e cinco operações; esses números são descritivos e não sustentam inferência estatística.

| Período | Custo/lado | Trades | Acerto | Payoff líquido | EV líquido/operação | DD adverso |
|---|---:|---:|---:|---:|---:|---:|
| Validação 2025 | 0,10% | 22 | 50,0% | 0,907 | -0,052% | 1,12% |
| Validação 2025 | 0,15% | 22 | 50,0% | 0,751 | -0,152% | 1,33% |
| Confirmação diagnóstica 2026 | 0,10% | 5 | 20,0% | 0,236 | -0,397% | 0,87% |
| Confirmação diagnóstica 2026 | 0,15% | 5 | 20,0% | 0,039 | -0,497% | 0,99% |

O gatilho fica abaixo de 70% de acerto, payoff 1:1 e EV líquido >1,2% em ambos os custos. O drawdown observado é menor que 10%, mas a amostra pequena não é prova de risco controlado. A meta matemática só era alcançável com o piso de risco de 1,5%, alvo 1,9R e acerto perto de 70%; o replay não se aproximou do acerto necessário.

## Reprodutibilidade e limites

O replay usou BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT perpétuos, candles de um minuto de janeiro/2024 a agosto/2026 e funding histórico. Stop fica além do extremo varrido, target bruto 1,9R, prazo máximo 60 minutos. Nenhuma ordem real ou chamada Jev foi enviada. A regra foi inspirada em sweep/reclaim, mas usa nível de 60 minutos e confirmação em cinco minutos; não é a mesma amostra temporal que o sweep de 24 horas em barras horárias. Ainda assim, esses dados já tinham sido pesquisados em outras resoluções e não são holdout de mercado intocado.

- Protocolo congelado: [futures_liquidity_sweep_protocol_2026-09-27.md](futures_liquidity_sweep_protocol_2026-09-27.md).
- Relatório completo: `results/futures_liquidity_sweep_20260927/research.json`.
- SHA-256 do código: `853ec88950c4c6d1f65e6d5b74971e5afd33d95e01c92ca0dbffbeb3a1179bad`.
- SHA-256 do protocolo: `33c825807e79ce63161add121d399a093260619a2ef96998c414961ed9e17e20`.
