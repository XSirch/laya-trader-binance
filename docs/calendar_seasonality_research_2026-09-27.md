# Replay exploratório: exposição Spot apenas durante a semana

Execução: 2026-09-27T07:37:25.722445+00:00 UTC. Período de operações: 2023-03-27T00:00:00+00:00 a 2026-08-29T00:00:00+00:00.

## Resultado

A regra fixa não atingiu o gate local em nenhum custo. O replay cobra compras e vendas em cada semana e não inclui spread ou slippage; todo o histórico já havia sido visto em pesquisas anteriores, portanto os números são exploratórios.

| Custo por lado | Regra: CAGR / retorno / DD horário / limite adverso | Buy-and-hold: CAGR / retorno / DD horário | Diferença final | Gate |
|---:|---:|---:|---:|---:|
| 0.15% | +2.08% / +7.31% / 71.36% / 71.45% | +35.08% / +180.11% / 65.63% | -61.69% | não |
| 0.25% | -8.05% / -24.98% / 77.38% / 77.45% | +35.00% / +179.55% / 65.63% | -73.16% | não |

## Resultados anuais por custo

Os anos inicial e final são parciais. CAGR e retornos são líquidos das taxas simuladas.

| Custo | Conta | Ano | Retorno |
|---:|---|---:|---:|
| 0.15% | Regra | 2023 (parcial) | +59.58% |
| 0.15% | Regra | 2024 | +31.77% |
| 0.15% | Regra | 2025 | -38.29% |
| 0.15% | Regra | 2026 (parcial) | -17.30% |
| 0.15% | Buy-and-hold | 2023 (parcial) | +114.81% |
| 0.15% | Buy-and-hold | 2024 | +90.65% |
| 0.15% | Buy-and-hold | 2025 | -18.37% |
| 0.15% | Buy-and-hold | 2026 (parcial) | -16.21% |
| 0.25% | Regra | 2023 (parcial) | +47.31% |
| 0.25% | Regra | 2024 | +18.64% |
| 0.25% | Regra | 2025 | -44.38% |
| 0.25% | Regra | 2026 (parcial) | -22.82% |
| 0.25% | Buy-and-hold | 2023 (parcial) | +114.59% |
| 0.25% | Buy-and-hold | 2024 | +90.65% |
| 0.25% | Buy-and-hold | 2025 | -18.37% |
| 0.25% | Buy-and-hold | 2026 (parcial) | -16.29% |

## Comparação por ativo

Custo por lado conforme o título da tabela. Cada sleeve começa com 25% do capital total.

### 0.15% por lado

| Ativo | Regra: retorno da parcela | DD horário | Limite adverso | Fim de semana médio bruto | Fins de semana positivos |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | +34.62% | 60.07% | 60.19% | +0.13% | 50.8% (179) |
| ETHUSDT | -36.11% | 76.98% | 77.17% | +0.19% | 54.2% (179) |
| BNBUSDT | -18.58% | 70.06% | 70.15% | +0.28% | 56.4% (179) |
| SOLUSDT | +49.31% | 83.51% | 83.56% | +0.48% | 55.3% (179) |
### 0.25% por lado

| Ativo | Regra: retorno da parcela | DD horário | Limite adverso | Fim de semana médio bruto | Fins de semana positivos |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | -5.89% | 64.11% | 64.16% | +0.13% | 50.8% (179) |
| ETHUSDT | -55.33% | 81.85% | 82.00% | +0.19% | 54.2% (179) |
| BNBUSDT | -43.08% | 72.27% | 72.42% | +0.28% | 56.4% (179) |
| SOLUSDT | +4.38% | 86.98% | 87.02% | +0.48% | 55.3% (179) |

## Custos e consistência

- Semanas completas negociadas: **179**.
- Exposição planejada: **71.43%** do tempo.
- Semanas positivas no custo base: **84 de 179** (46.9%); sequência perdedora mais longa: **7 semanas**.
- Execuções simuladas por custo: **1432 lados de ordem** na carteira; cada lado representa uma conta em um ativo.
- Custos pagos / giro de cotações no cenário base: **0.856332 / 570.888002** unidades sobre capital inicial 1.
- Meses completos positivos no custo base: **20 de 40**; sequência perdedora mais longa: **6 meses**.
- O limite adverso aplica as mínimas de cada candle enquanto há posição. É uma estimativa conservadora de marcação, não um fill ou caminho intrabar provado.
- A regra usa somente o calendário. Não há ajuste ML: cerca de 180 fins de semana não justificam pesquisar combinações ou treinar um gate sem multiplicar a seleção.

## Dados e reprodutibilidade

- Arquivos Binance mensais conferidos pelo manifesto: **176**.
- Horários comuns: **32135**; lacunas arquivadas antes do início: **4**.
- Símbolos: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT; candles de 1h em UTC.
- Identidade agregada dos arquivos: `ba543fd02d537a093e8d6b10bb76d959854533661dca42c33cf6f7c64fbdcb31`.
- Hash do código: `006797907657b9c1cdd093ca1f354d9f472ce1ba05a093c3e70c1d7bfca9d446`.
- Hash do protocolo: `95a2cb5c8b17c6d5b99a12bd7d1a9a3090bee7f42eb85e5a4454d624ba837dad`.
- Hash das fontes: `1c8a45ad1301dbb8849377e8c3e6db13e514a29c2a17db9625ad875208c62ad0`.
- Ledger de cada fill e retornos por ciclo semanal preservados no JSON; curvas horárias totais e por ativo estão nos CSVs referenciados no JSON.
- Nenhuma ordem real, chamada JEV, download ou teste de software foi executado.

## Conclusão

A hipótese não é aprovada. Uma diferença histórica favorável, se presente, não demonstraria que o efeito continua existindo: calendário, custos reais, spread e slippage precisam ser observados prospectivamente antes de qualquer decisão de trading. Não use este replay para autorizar capital real.
