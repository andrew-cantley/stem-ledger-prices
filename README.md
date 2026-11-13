# Stem Ledger price feed

Once a month this reads FiftyFlowers' public prices for the flowers in `products.json`
and saves them to `prices.json`. Stem Ledger reads that file by itself. No AI is involved.

## Using it in Stem Ledger

In Stem Ledger: **Generate Quote > Pricing settings > Automatic price feed address**. Paste

    https://raw.githubusercontent.com/andrew-cantley/stem-ledger-prices/main/prices.json

and click **Check now**. After that the tool checks by itself about every three weeks.
Prices typed in by hand are never overwritten.

## Running it by hand

**Actions** tab > **Update flower prices** > **Run workflow**. It also runs on the 1st of
each month.

## Changing which product stands for a flower

Edit `products.json` (the pencil icon) and replace that flower's `url` with a different
FiftyFlowers product page address. Flowers without a page are listed under
`_not_found_at_fiftyflowers`; Stem Ledger keeps its own estimates for those.

## What the numbers mean

- `perStem` is the price per stem in the smallest pack, which is what a small order pays.
- `perStemBulk` is the price per stem in the largest pack, for reference.
- A range such as "3-6 stems in a bunch" counts as the middle (4.5).
- Anything sold one piece at a time, such as a garland, counts as one stem.
