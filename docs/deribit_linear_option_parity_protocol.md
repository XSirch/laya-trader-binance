# Deribit linear-option parity: fixed public-book screen

Freeze this read-only screen before the first option or matched-future book read.
Use Deribit's active BTC_USDC and ETH_USDC linear options expiring on
2026-10-30 and 2026-12-25, with their same-expiry linear futures. For each of
the four asset/expiry groups, fetch the public index price and the active
instrument metadata, then select exactly the three strikes nearest that index
which have both a call and a put. Break distance ties toward the lower strike.
Record a missing expiry or strike as missing; do not substitute another expiry.
Do not change the selection, assumptions or threshold after reading books.

For each selected strike, read the call, put and matching future 100-level
books concurrently, followed by server time. Require open instruments, all
required bid/ask sides, book timestamps 0-10 seconds old at server time and
local receive times within five seconds of one another. Failed, stale or
missing reads fail the case. Save complete public responses and timestamps.

Evaluate both parity directions at intended underlying notionals of 1,000
and 2,000 USDC, rounded down to the option minimum amount as an illustrative
lot step; require the future minimum and full displayed depth in all three
legs. Do not use mid prices or assume maker fills. Per underlying coin:

- Sell call at bid, buy put at ask, buy same-expiry future at ask:
  `K - future_ask + call_bid - put_ask` at expiry.
- Buy call at ask, sell put at bid, sell same-expiry future at bid:
  `future_bid - K + put_bid - call_ask` at expiry.

Walk the books for each quantity. Charge each option 0.03% taker and the future
0.035% taker on the greater of index, strike and traded future price. Also
reserve 0.015% per option and 0.025% on the future for expiry fees even though
actual netting may lower them. Add a 0.25% underlying-notional execution and
mark uncertainty stress, plus 1% annual capital charge on 1.25 times the
underlying notional plus any net option premium paid. These stresses are
illustrative, not maximum loss bounds. Use the exact common settlement index;
do not add a separate spot-exit leg. Require positive stressed conditional
cash and at least 4% annualized on reserved capital for **both** sizes in the
same direction. One quote is only a preliminary screen and cannot establish
fillable three-leg execution, margin safety or robust realized profit.

No order, transfer or shadow position is authorized. The user's Deribit
eligibility, fee tier, account margin mode and USDC liquidity are unknown.

Primary sources: [Deribit production API](https://docs.deribit.com/),
[linear USDC options](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options),
[linear futures](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures),
[fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).
