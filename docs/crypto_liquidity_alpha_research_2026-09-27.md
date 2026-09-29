# Sinal semanal de liquidez nativa de cripto

Execução: 2026-09-27T16:55:55.650439Z. Replay histórico exploratório; nenhuma ordem foi enviada.

## Resultado do modelo

A feature usa apenas crescimento de oferta de stablecoins atreladas ao USD, defasada em 96 horas. O ativo negociado em todos os casos é um dos quatro pares Spot listados abaixo.

| Janela | Semanas/p pares | Price-only MSE | Liquidez cripto MSE | Skill incremental | Acerto direcional com liquidez |
|---|---:|---:|---:|---:|---:|
| walk_forward | 452 / 113 | 0.00819804 | 0.00836908 | -2.09% | 48.89% |
| development_2024 | 108 / 27 | 0.01008372 | 0.01038594 | -3.00% | 55.56% |
| holdout_2025_plus | 344 / 86 | 0.00760603 | 0.00773587 | -1.71% | 46.80% |

## Carteiras Spot long/caixa

CAGR e drawdown em %. A coluna adversa usa as mínimas horárias enquanto a carteira tem exposição; não prova fills nem o caminho intrabar.

| Janela | Custo/lado | Regra | CAGR | Retorno | DD observado | DD adverso | Exposição | Ordens |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| walk_forward | 0.15% | price_plus_stablecoin_liquidity | -6.47% | -13.48% | 59.60% | 60.25% | 72.1% | 124 |
| walk_forward | 0.15% | price_only | -5.81% | -12.16% | 59.73% | 60.34% | 75.4% | 112 |
| walk_forward | 0.15% | buy_hold | -2.35% | -5.03% | 61.96% | 62.36% | 100.0% | 8 |
| walk_forward | 0.15% | cash | +0.00% | +0.00% | 0.00% | 0.00% | 0.0% | 0 |
| walk_forward | 0.30% | price_plus_stablecoin_liquidity | -6.66% | -13.86% | 53.83% | 54.50% | 63.3% | 138 |
| walk_forward | 0.30% | price_only | +1.44% | +3.14% | 55.79% | 56.27% | 68.8% | 130 |
| walk_forward | 0.30% | buy_hold | -2.49% | -5.31% | 61.96% | 62.36% | 100.0% | 8 |
| walk_forward | 0.30% | cash | +0.00% | +0.00% | 0.00% | 0.00% | 0.0% | 0 |
| development_2024 | 0.15% | price_plus_stablecoin_liquidity | +75.29% | +33.70% | 30.81% | 31.60% | 79.6% | 28 |
| development_2024 | 0.15% | price_only | +44.98% | +21.19% | 34.46% | 36.19% | 85.2% | 32 |
| development_2024 | 0.15% | buy_hold | +71.16% | +32.06% | 34.20% | 35.94% | 100.0% | 8 |
| development_2024 | 0.15% | cash | +0.00% | +0.00% | 0.00% | 0.00% | 0.0% | 0 |
| development_2024 | 0.30% | price_plus_stablecoin_liquidity | +55.95% | +25.85% | 30.45% | 31.66% | 74.1% | 32 |
| development_2024 | 0.30% | price_only | +96.10% | +41.69% | 30.48% | 32.28% | 76.9% | 42 |
| development_2024 | 0.30% | buy_hold | +70.17% | +31.66% | 34.20% | 35.94% | 100.0% | 8 |
| development_2024 | 0.30% | cash | +0.00% | +0.00% | 0.00% | 0.00% | 0.0% | 0 |
| holdout_2025_plus | 0.15% | price_plus_stablecoin_liquidity | -23.22% | -35.31% | 59.43% | 60.10% | 69.8% | 96 |
| holdout_2025_plus | 0.15% | price_only | -16.36% | -25.50% | 59.86% | 60.53% | 72.4% | 84 |
| holdout_2025_plus | 0.15% | buy_hold | -17.93% | -27.80% | 62.31% | 62.72% | 100.0% | 8 |
| holdout_2025_plus | 0.15% | cash | +0.00% | +0.00% | 0.00% | 0.00% | 0.0% | 0 |
| holdout_2025_plus | 0.30% | price_plus_stablecoin_liquidity | -20.77% | -31.86% | 53.72% | 54.26% | 59.9% | 106 |
| holdout_2025_plus | 0.30% | price_only | -15.91% | -24.85% | 54.89% | 55.50% | 66.3% | 92 |
| holdout_2025_plus | 0.30% | buy_hold | -18.08% | -28.02% | 62.31% | 62.72% | 100.0% | 8 |
| holdout_2025_plus | 0.30% | cash | +0.00% | +0.00% | 0.00% | 0.00% | 0.0% | 0 |

## Decisão

A liquidez agregada de stablecoins não atingiu simultaneamente os limites retrospectivos congelados. Registrar este modelo como rejeitado ou inconclusivo conforme o erro preditivo e o PnL; não retunar esta amostra.

Candidata atingiu a meta retrospectiva congelada nos períodos e custos exigidos: **false**. Meta de consistência confirmatória e prontidão para operar: **não demonstradas**.

O endpoint não fornece vintages históricas, portanto o atraso de 96 horas não elimina possíveis revisões dos dados. As features podem representar uma variável endógena: retornos cripto também influenciam a emissão de stablecoins. A avaliação repete períodos de preço já estudados no projeto. Custos, spread e slippage são hipóteses fixas, não fills observados.

## Dados e reprodutibilidade

- Pares Spot negociáveis: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT.
- API: https://stablecoins.llama.fi/stablecoincharts/all; registros válidos: 3225 de 3225; observações ausentes no campo USD-pegged: 0.
- Série observada: 2017-11-29T00:00:00Z a 2026-09-27T00:00:00Z; SHA-256: `d3a1c35db255b36b0b02934195fbef10c8249e4fdce0234639de2423350618d9`.
- Manifesto Binance Spot: `5eba664095505668a66a6ba152a0af3c516b6a2a0d09ba58687120b91dee8e05`; protocolo: `e0d51a01c222b9cb0a28a3530596d825252243eff8348a32c2683f01cdac0577`; fontes: `b1e57a1fe77dafd5a500859fa99982e332f337e065221f8318911161f5e7b3d0`; código: `7a685b956f27c5c267da554e49517c3ffc2c5a9877e8bbba18dee59e0bab1c28`.
- Scikit-learn: `1.9.1`; Python: `3.13.9`.
- Nenhuma stablecoin foi negociada. Nenhum ETF/produto não cripto, contrato futuro, ordem real, chamada JEV ou alteração no paper watcher foi usado.
- Reproduzir o estudo com `.venv\Scripts\python.exe -m jev_trader.crypto_liquidity_alpha_research`; o runner exige que o SHA-256 do payload congelado continue igual a `d3a1c35db255b36b0b02934195fbef10c8249e4fdce0234639de2423350618d9`.
