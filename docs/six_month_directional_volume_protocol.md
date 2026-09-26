# Directional trade-volume diagnostic for the six-month basis rule

Specified after the five-minute aggregate-volume replay passed. This is a post-result diagnostic of the same ten historical legs, not an independent validation or a new selection rule.

## Fixed calculation

- Keep the 1,000 USDT illustrative account, the five completed BTC/ETH half-years, the frozen wallet and cost assumptions, and the 00:00-00:04 UTC five-minute limit from `docs/six_month_volume_window_protocol.md`.
- Read the `volume` and `taker_buy_base_volume` fields from the same SHA256/CRC-verified spot and USD-M delivery-future one-minute archives. Set taker-sell base volume to `volume - taker_buy_base_volume`; reject missing, negative or inconsistent values.
- For entry, compare the preliminary base quantity from the first positive-volume spot high with cumulative spot taker-buy volume and cumulative future taker-sell volume. The later first threshold minute is the common entry deadline.
- Recompute entry prices as the maximum traded spot high and minimum traded future low through that common deadline. Use the resulting actual quantity for exit. Compare it with cumulative spot taker-sell volume and future taker-buy volume, then set the common exit deadline analogously.
- If any side lacks same-direction trade volume by 00:04, report the leg as unavailable under this diagnostic and do not calculate a whole-account return. Otherwise replay with the adverse minute prices through each common deadline, the existing 19 bps per side in each market, and the unchanged daily margin and wallet stress.
- Also record the earliest threshold minute for each of the four sides, and whether the direction-specific threshold was met by the earlier aggregate-volume completion deadline.

Historical same-direction trades demonstrate activity, not bid/ask depth, queue priority, available order size, or a fill guarantee. Additional hypothetical orders could have traded even if the historical same-direction volume was lower. This diagnostic cannot prove a live executable edge or authorize live orders.
