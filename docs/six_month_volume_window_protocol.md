# Five-minute cumulative-volume diagnostic for the six-month basis rule

Specified after the original six-month replay passed and after the 2026 H1 BTC entry's first-minute volume shortfall was observed. This is a post-result execution stress, not an independent validation or a new trade-selection rule.

## Fixed fill-window approximation

- Retain exactly the five completed BTC/ETH half-years, 0.5 normalized spot allocation per leg, separate 1.05 spot and 3.00 futures wallets, 19 basis points per side in each market, daily-high plus 10% future mark shock, and 5% assumed maintenance from `docs/six_month_basis_protocol.md`.
- Use an illustrative 1,000 USDT total account. The first positive-volume spot minute's high gives a preliminary base-asset quantity equal to `0.5 / 4.05 * 1000 / spot_high`. This is at least as large as the final quantity when the adverse entry price is the maximum high over the waiting window.
- Beginning at 00:00 UTC, accumulate positive-volume one-minute spot and future bars separately. The earliest minute by which each market's aggregate base volume reaches the preliminary entry quantity is its entry completion minute. Use the later of the two completion minutes as a common completion deadline.
- At exit, repeat with the actual base-asset quantity opened, scaled to the same illustrative account. If any of the four market-side windows cannot accumulate that quantity by 00:04 UTC, mark that leg unavailable; do not assign it an executable return.
- For entry, buy spot at the maximum spot high and short the future at the minimum future low across positive-volume bars from 00:00 through the common completion minute. At exit, sell spot at the minimum low and cover the future at the maximum high over its common completion window. Both positions are assumed complete by that minute; the five-minute price range is a conservative bound on observed trades, not a bid/ask or queue model.

Replay the complete account with these four changed execution prices and the otherwise frozen wallet/risk rules. Report every completion delay, the maximum required wait, the net return in every half-year, source checksums, and whether the original historical research gate still passes. The gate's result is a sensitivity diagnostic because it follows the earlier outcome. Aggregate traded volume does not prove our order could fill or that the extreme price was available at the requested quantity. No live orders are authorized.
