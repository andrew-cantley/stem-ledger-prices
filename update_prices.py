#!/usr/bin/env python3
"""Builds prices.json for Stem Ledger from FiftyFlowers' public product pages.

No AI and no account needed. For every flower in products.json it reads the product's
public data, finds each pack size and price, and records the price per stem.
Standard library only, so it runs anywhere Python 3 does.

Run:  python3 update_prices.py
"""
import datetime
import json
import re
import sys
import time
import urllib.request

PRODUCTS_FILE = "products.json"
OUTPUT_FILE = "prices.json"
USER_AGENT = "StemLedgerPriceCheck/1.0 (monthly personal price check)"
PAUSE_SECONDS = 1.5


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_product(url):
    """Shopify stores publish each product as <url>.js and <url>.json. Try both."""
    base = url.split("?")[0].rstrip("/")
    last_error = None
    for suffix in (".js", ".json"):
        try:
            data = fetch_json(base + suffix)
            return data.get("product", data)
        except Exception as err:  # try the next form
            last_error = err
    raise last_error


def load_collection_products(url):
    """A collection address lists many products (one per color). Shopify publishes the list."""
    base = url.split("?")[0].rstrip("/")
    return fetch_json(base + "/products.json?limit=250").get("products", [])


def pick_from_collection(url, per_bunch_hint=None, prefer=None):
    """Chooses one product to stand for the flower: the white or ivory one when there is one
    (colors usually cost the same), otherwise the first that has a readable pack and price."""
    words = [w.lower() for w in (prefer or ["white", "ivory", "cream"])]
    products = load_collection_products(url)
    ranked = sorted(products, key=lambda p: 0 if any(w in str(p.get("title", "")).lower() for w in words) else 1)
    for product in ranked:
        if options_for(product, per_bunch_hint):
            return product
    titles = [str(p.get("title")) + " :: " + " / ".join(str(v.get("title")) for v in p.get("variants", [])[:3]) for p in products[:4]]
    raise ValueError("no product in the collection has a readable pack | %d products | %s" % (len(products), titles))


def is_collection(url):
    return "/collections/" in url and "/products/" not in url


def to_dollars(price):
    """The .js form gives whole cents (38999); the .json form gives a string ("389.99")."""
    if isinstance(price, bool) or price is None:
        return None
    if isinstance(price, int):
        return price / 100.0
    try:
        return float(str(price).replace("$", "").replace(",", ""))
    except ValueError:
        return None


RANGE = r"(\d[\d,]*(?:\.\d+)?)(?:\s*(?:-|\u2013|\u2014|to)\s*(\d[\d,]*(?:\.\d+)?))?"


def _avg(lo, hi):
    """'3-6' counts as 4.5: when a range is given, use the middle of it."""
    lo = float(lo.replace(",", ""))
    return (lo + float(hi.replace(",", ""))) / 2.0 if hi else lo


def stems_in(text):
    """'150 Stems' -> 150.  '3-6 stems' -> 4.5.  '10 Garlands' -> 10.  No count -> None."""
    # Anything sold one piece at a time counts as one stem: a garland, a strand, a leaf, a bloom.
    m = re.search(RANGE + r"\s*(?:stems?|garlands?|strands?|vines?|leaves|leaf|blooms?|heads?|pieces?|branches|branch)\b", text or "", re.I)
    if m:
        return _avg(m.group(1), m.group(2))
    # FiftyFlowers usually leads with the count: "25 Roses (1 Bunch)", "10 Phalaenopsis Orchid Stems".
    # A leading number is the number of pieces, unless it is counting bunches, boxes or packs.
    m = re.match(r"\s*" + RANGE + r"\s+(?!(?:grower'?s?\s+)?(?:bunch|box|pack|case|bundle))[A-Za-z]", text or "", re.I)
    return _avg(m.group(1), m.group(2)) if m else None


def bunches_in(text):
    m = re.search(RANGE + r"\s*(?:grower'?s?\s+)?bunch(?:es)?\b", text or "", re.I)
    return _avg(m.group(1), m.group(2)) if m else None


def stems_per_bunch(product):
    """Looks in the product description for 'Stems Per Bunch: 3-6' or '3 to 6 stems per bunch'."""
    text = re.sub(r"<[^>]+>", " ", str(product.get("description") or product.get("body_html") or ""))
    m = re.search(r"stems?\s*per\s*bunch\D{0,25}?" + RANGE, text, re.I)
    if not m:
        m = re.search(RANGE + r"\s*stems?\s*(?:per|in\s+a|in\s+each|a|each)\s*(?:grower'?s?\s+)?bunch", text, re.I)
    return _avg(m.group(1), m.group(2)) if m else None


def options_for(product, per_bunch_hint=None):
    # stems per bunch: from the page if it says, otherwise the figure noted in products.json
    per_bunch = stems_per_bunch(product) or per_bunch_hint
    out = []
    for v in product.get("variants", []):
        label = str(v.get("title") or v.get("option1") or "")
        stems = stems_in(label)
        if not stems:  # sold by the bunch: bunches x stems per bunch
            bunches = bunches_in(label)
            if bunches and per_bunch:
                stems = bunches * per_bunch
        price = to_dollars(v.get("price"))
        if stems and price and price > 0:
            # the variant id lets Stem Ledger build a ready-filled cart link
            out.append({"stems": stems, "price": price, "id": v.get("id"), "available": v.get("available", True)})
    return sorted(out, key=lambda o: o["stems"])


def main():
    with open(PRODUCTS_FILE, encoding="utf-8") as f:
        config = json.load(f)
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            previous = json.load(f).get("prices", {})
    except (OSError, ValueError):
        previous = {}

    today = datetime.date.today().isoformat()
    prices, failed = {}, []
    for flower_id, item in config["products"].items():
        try:
            if is_collection(item["url"]):
                product = pick_from_collection(item["url"], item.get("stemsPerBunch"), item.get("prefer"))
            else:
                product = load_product(item["url"])
            options = options_for(product, item.get("stemsPerBunch"))
            if not options:
                labels = [" ".join(str(x) for x in [v.get("title"), v.get("option1"), v.get("option2")] if x) + " @" + str(v.get("price")) for v in product.get("variants", [])][:4]
                text = re.sub(r"<[^>]+>", " ", str(product.get("description") or product.get("body_html") or ""))
                hint = " ".join(re.findall(r"[^.]{0,60}(?:bunch|stem)[^.]{0,60}", text, re.I)[:3])
                raise ValueError("no pack with a stem count and price | variants: %s | text: %s" % (labels, hint[:300]))
            small, bulk = options[0], options[-1]
            prices[flower_id] = {
                # what a small order pays: the smallest pack. The tool uses this one.
                "perStem": round(small["price"] / small["stems"], 2),
                "pack": "%g stems for $%.2f" % (small["stems"], small["price"]),
                # the best price, from the largest pack, for reference
                "perStemBulk": round(bulk["price"] / bulk["stems"], 2),
                "bulkPack": "%g stems for $%.2f" % (bulk["stems"], bulk["price"]),
                # every pack on offer, so the tool can cost the pack an order would really buy
                "packs": [{"stems": o["stems"], "price": round(o["price"], 2), "id": o.get("id")} for o in options],
                "product": product.get("title") or item.get("product", ""),
                "flower": item.get("flower", ""),
                "url": ("https://fiftyflowers.com/products/" + product["handle"]) if is_collection(item["url"]) and product.get("handle") else item["url"],
                "asOf": today,
            }
            print("ok    %-5s %-34s $%.2f a stem" % (flower_id, item.get("flower", "")[:34], prices[flower_id]["perStem"]))
        except Exception as err:
            failed.append(flower_id)
            if flower_id in previous:  # keep last month's price rather than lose it
                prices[flower_id] = previous[flower_id]
            print("FAIL  %-5s %-34s %s" % (flower_id, item.get("flower", "")[:34], err))
        time.sleep(PAUSE_SECONDS)

    fresh = len(config["products"]) - len(failed)
    if fresh == 0:
        print("\nNothing could be read. Leaving %s untouched." % OUTPUT_FILE)
        return 1

    result = {
        "app": "stem-ledger-prices",
        "source": config.get("source", "FiftyFlowers"),
        "date": today,
        "shippingIncluded": bool(config.get("shippingIncluded", False)),
        "prices": prices,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True)
        f.write("\n")
    print("\nWrote %s: %d read fresh, %d kept from before or missing." % (OUTPUT_FILE, fresh, len(failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
