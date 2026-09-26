# Binance COIN-M delivery: fixed public-book universe screen

Frozen before reading any COIN-M delivery order book for this study. Official
exchange metadata currently lists exactly ten active quarterly contracts:
BNB, BTC, ETH, SOL and XRP versus USD, each for December 25, 2026 and March
26, 2027. Screen all ten, including any failed API read; do not substitute
another symbol or maturity. The instrument is inverse and settled in its
base coin. This is a separate hypothesis from the inspected USDT-M contracts.

- For each contract and each intended 500/1,000 USDT position, round the
  number of contracts **down** to the integer/lot quantity whose USD face
  does not exceed the target. Read a 100-level futures bid book and matching
  spot USDT ask book. For each filled futures bid level, compute the coin
  needed to hedge its USD face as `contracts * contract_size / bid_price`;
  sum across levels. Round the spot purchase **up** to the spot lot step.
  Require all contracts and the spot purchase to fit displayed depth and
  exchange quantity/notional filters. Any unhedged excess spot from rounding
  receives zero value at exit in this screen.
- Buy the spot coin, transfer it as COIN-M collateral, short the inverse
  future and hold until cash settlement. At expiry, matched coin collateral
  plus inverse short P&L has USD index value equal to the futures USD face,
  before fees, assuming no liquidation or exchange interruption. The screen
  uses that USD face as the **conditional** spot-sale receipt before costs;
  it does not infer a realized fill or a safe margin path. Require spot and
  future book receive times within five seconds, the future book's `T`
  within ten seconds of the later COIN-M server clock, and positive time to
  delivery. One failed read/leg fails that contract.
- Charge these illustrative rates without retuning after the books: 0.10%
  spot taker at entry; 0.05% COIN-M future taker at entry, valued at **twice**
  the entry spot price to stress its coin-denominated fee; 0.05% futures
  settlement fee on USD face; 0.10% spot taker at exit; 0.10% exit slippage;
  0.10% adverse spot/index mismatch; another 0.25% USD-face uncertainty
  stress; and a 1.00% annual capital charge on 1.025 times entry spot cost
  reserved through delivery. The coin bought in excess of the exact hedge
  is included in entry cost but assigned no terminal value. Actual fees,
  transfer eligibility, liquidation engine, spot-sale book and taxes are
  unknown. These stresses are scenarios, not guaranteed worst cases.
- A contract passes this **preliminary** screen only if both intended sizes
  have timely, fully displayed books, valid lot/notional rules, positive
  conditional net cash, and at least 4% annualized conditional net return
  on the illustrative reserved capital. Any passing contract needs a newly
  frozen, repeated forward-book observation and account-specific review;
  no order is authorized. Failure at this stage ends this fixed snapshot
  without selecting a weaker post-hoc threshold.

Primary sources: [Binance COIN-M market-data API](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Get-Funding-Info), [inverse contract sizing and settlement](https://www.binance.com/en-NG/support/faq/detail/d33f37e2c7fe4da3b35ffc904e8fbab5), [quarterly delivery and P&L](https://www.binance.com/en-AE/support/faq/detail/a3401595e1734084959c61491bc0dbe3), [COIN-M fee announcement](https://www.binance.com/en/support/announcement/detail/f4433fc2964b4c92998132f433edff7c), [Binance spot REST API](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md).
