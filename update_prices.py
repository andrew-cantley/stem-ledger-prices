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


NOT_A_PLAIN_BUNCH = re.compile(r"kit|garland|centerpiece|mix|collection|combo|dried|tinted|dyed|airbrush|painted|preserved|wreath|bouquet|diy|box|petal|assort|pack\b", re.I)


def pick_from_collection(url, per_bunch_hint=None, prefer=None, match=None):
    """Chooses one product to stand for the flower: a plain bunch (no kits, garlands or mixes)
    whose name contains the flower, the white or ivory one when there is one (colors usually
    cost the same), otherwise the first that has a readable pack and price."""
    words = [w.lower() for w in (prefer or ["white", "ivory", "cream"])]
    products = load_collection_products(url)
    plain = [p for p in products if not NOT_A_PLAIN_BUNCH.search(str(p.get("title", "")))
             and (not match or any(m.lower() in str(p.get("title", "")).lower() for m in match))]
    ranked = sorted(plain, key=lambda p: 0 if any(w in str(p.get("title", "")).lower() for w in words) else 1)
    for product in ranked:
        if options_for(product, per_bunch_hint):
            return product
    titles = [str(p.get("title")) + " :: " + " / ".join(str(v.get("title")) for v in p.get("variants", [])[:3]) for p in products[:4]]
    raise ValueError("no plain product in the collection has a readable pack | %d products | %s" % (len(products), titles))


def list_collections(config):
    """python3 update_prices.py --list : shows what each collection address holds."""
    for flower_id, item in config["products"].items():
        if not is_collection(item["url"]):
            continue
        print("\n== %s %s" % (flower_id, item.get("flower")))
        for p in load_collection_products(item["url"]):
            print("   %s | %s | %s" % (p.get("handle"), p.get("title"), " / ".join("%s $%s" % (v.get("title"), v.get("price")) for v in p.get("variants", [])[:4])))
        time.sleep(PAUSE_SECONDS)


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


def bare_count(product, variant, bare=None):
    """Some stores label a size with just a number ("50"). The option's own name says what it
    counts ("Stems: 50"); a pin can also say it. Returns (stems, bunches)."""
    names = [str(o.get("name", "") if isinstance(o, dict) else o).lower() for o in product.get("options", [])]
    for i, key in enumerate(("option1", "option2", "option3")):
        value = str(variant.get(key) or "").strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?", value):
            continue
        name = names[i] if i < len(names) else ""
        kind = bare or ("stems" if "stem" in name else "bunches" if "bunch" in name else None)
        if kind == "stems":
            return float(value), None
        if kind == "bunches":
            return None, float(value)
    return None, None


def options_for(product, per_bunch_hint=None, per_piece=None, unit=None, bare=None):
    # stems per bunch: from the page if it says, otherwise the figure noted in products.json
    per_bunch = stems_per_bunch(product) or per_bunch_hint
    best = {}
    for v in product.get("variants", []):
        label = " ".join(str(x) for x in [v.get("title"), v.get("option1"), v.get("option2"), v.get("option3")] if x)
        stems = stems_in(label)
        if not stems:  # sold by the bunch: bunches x stems per bunch
            bunches = bunches_in(label)
            if not bunches:
                stems, bunches = bare_count(product, v, bare)
            if not stems and bunches and per_bunch:
                stems = bunches * per_bunch
        price = to_dollars(v.get("price"))
        if stems and price and price > 0:
            # the variant id lets Stem Ledger build a ready-filled cart link
            option = {"stems": stems, "price": price, "id": v.get("id")}
            if per_piece:  # a garland sold by the foot: each foot stands for about this many stems
                option["label"] = "%g %s" % (stems, unit or "pieces")
                option["stems"] = stems * per_piece
            # the same count offered at several stem lengths: keep the cheapest
            if option["stems"] not in best or price < best[option["stems"]]["price"]:
                best[option["stems"]] = option
    return sorted(best.values(), key=lambda o: o["stems"])


def pack_list(options):
    out = []
    for o in options:
        pack = {"stems": o["stems"], "price": round(o["price"], 2), "id": o.get("id")}
        if o.get("label"):
            pack["label"] = o["label"]
        out.append(pack)
    return out


# ---- other stores: read the whole public catalog once, then match flowers by name ----

def load_catalog(site, max_pages=30):
    products, page = [], 1
    while page <= max_pages:
        batch = fetch_json("%s/products.json?limit=250&page=%d" % (site.rstrip("/"), page)).get("products", [])
        products.extend(batch)
        if len(batch) < 250:
            break
        page += 1
        time.sleep(PAUSE_SECONDS)
    return products


NOT_PLAIN = re.compile(r"kit|garland|centerpiece|mix|combo|collection|dried|tinted|dyed|airbrush|painted|preserved|wreath|bouquet|diy|box|petal|assort|pack\b|bundle|artificial|faux|silk|rainbow|glitter|subscription|sample|vase|arrangement|package|wedding flowers|potted|plant\b|seed|crown|novelty|bicolor", re.I)
WHITE = ("white", "ivory", "cream")


def _has(title, group):
    return any(word in title for word in group.split("|"))


def match_supplier(catalog, flowers):
    """One product per flower: its name holds every required word, none of the excluded ones,
    and no other flower's name (so 'Lilac Roses' is a rose, and 'Peony Tulips' is neither)."""
    primary = {fid: rule["all"][0] for fid, rule in flowers.items()}
    out = {}
    titles = [(str(p.get("title", "")).lower(), p) for p in catalog]
    for fid, rule in flowers.items():
        own = " ".join(rule["all"])
        candidates = []
        for title, product in titles:
            if NOT_PLAIN.search(title) or not all(_has(title, g) for g in rule["all"]):
                continue
            if any(word in title for word in rule.get("not", [])):
                continue
            # another flower's name in the title, unless that name is part of this flower's own
            if any(other != fid and _has(title, words) and not any(w in own for w in words.split("|")) for other, words in primary.items()):
                continue
            # a longer, more specific flower also fits (spray rose, garden rose): leave it to that one
            if any(other != fid and all(_has(title, g) for g in flowers[other]["all"]) and len(" ".join(flowers[other]["all"])) > len(own) for other in flowers):
                continue
            options = options_for(product)
            if options:
                small = options[0]
                # plain white first, then white with a second color, then anything else
                tier = 2 if not any(w in title for w in WHITE) else (1 if (" and " in title or "&" in title) else 0)
                candidates.append((tier, small["price"] / small["stems"], product, options))
        if candidates:
            candidates.sort(key=lambda c: (c[0], c[1]))
            _, _, product, options = candidates[0]
            out[fid] = {"perStem": round(options[0]["price"] / options[0]["stems"], 2), "packs": pack_list(options),
                        "product": product.get("title", ""), "handle": product.get("handle", "")}
    return out


def compact_catalog(catalog):
    """Every plain product with a readable pack: [name, handle, [[stems, price, id], ...]].
    Stem Ledger searches this for flowers she adds herself, so they get prices too."""
    out = []
    for product in catalog:
        title = str(product.get("title", ""))
        if NOT_PLAIN.search(title.lower()):
            continue
        options = options_for(product)[:6]
        if options:
            out.append([title, product.get("handle", ""), [[o["stems"], round(o["price"], 2), o.get("id")] for o in options]])
            continue
        # sold by the bunch with no stem count on the listing: keep the bunch options, so the
        # tool can price it using the stems per bunch it already knows for that flower
        bunch_options = []
        for v in product.get("variants", [])[:6]:
            label = " ".join(str(x) for x in [v.get("title"), v.get("option1")] if x)
            bunches, price = bunches_in(label), to_dollars(v.get("price"))
            if bunches and price and price > 0:
                bunch_options.append([bunches, round(price, 2), v.get("id")])
        if bunch_options:
            out.append([title, product.get("handle", ""), [], bunch_options])
    return out


def read_suppliers(today, catalogs):
    try:
        with open("suppliers.json", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        return {}
    result = {}
    for sup in config.get("suppliers", []):
        try:
            catalog = load_catalog(sup["site"])
            catalogs[sup["name"]] = {"site": sup["site"], "products": compact_catalog(catalog)}
            found = match_supplier(catalog, config["flowers"])
            # product pages chosen by hand win over the name match
            for fid, pin in config.get("pins", {}).get(sup["name"], {}).items():
                handle = pin["handle"]
                product = next((p for p in catalog if p.get("handle") == handle), None)
                try:
                    if product is None:
                        product = load_product("%s/products/%s" % (sup["site"].rstrip("/"), handle))
                    options = options_for(product, pin.get("stemsPerBunch"), bare=pin.get("bare"))
                    if not options:
                        labels = [" ".join(str(x) for x in [v.get("title"), v.get("option1")] if x) + " $" + str(v.get("price")) for v in product.get("variants", [])][:4]
                        raise ValueError("no stem count on the listing | %s" % labels)
                    found[fid] = {"perStem": round(options[0]["price"] / options[0]["stems"], 2), "packs": pack_list(options),
                                  "product": product.get("title", ""), "handle": product.get("handle", handle), "pinned": True}
                except Exception as err:
                    print("   PIN FAIL %-5s %-28s %s" % (fid, handle[:28], str(err)[:230]))
            for fid, entry in found.items():
                entry["url"] = "%s/products/%s" % (sup["site"].rstrip("/"), entry.pop("handle"))
                entry["flower"] = config["flowers"][fid].get("flower", "")
            result[sup["name"]] = {"site": sup["site"], "asOf": today, "prices": found}
            print("\n%s: %d products read, %d flowers matched" % (sup["name"], len(catalog), len(found)))
            for fid in sorted(found, key=lambda x: int(x)):
                print("   %-5s %-30s $%-6.2f %s | %s" % (fid, found[fid]["flower"][:30], found[fid]["perStem"], found[fid]["product"][:60], "%g stems $%.2f" % (found[fid]["packs"][0]["stems"], found[fid]["packs"][0]["price"])))
        except Exception as err:
            print("\nFAIL  %s: %s" % (sup["name"], err))
        time.sleep(PAUSE_SECONDS)
    return result


def main():
    with open(PRODUCTS_FILE, encoding="utf-8") as f:
        config = json.load(f)
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            previous = json.load(f).get("prices", {})
    except (OSError, ValueError):
        previous = {}

    if "--list" in sys.argv:
        list_collections(config)
        return 0

    today = datetime.date.today().isoformat()
    prices, failed, catalogs = {}, [], {}
    for flower_id, item in config["products"].items():
        try:
            if is_collection(item["url"]):
                product = pick_from_collection(item["url"], item.get("stemsPerBunch"), item.get("prefer"), item.get("match"))
            else:
                product = load_product(item["url"])
            options = options_for(product, item.get("stemsPerBunch"), item.get("stemsPerPiece"), item.get("unit"))
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
                "packs": pack_list(options),
                "product": product.get("title") or item.get("product", ""),
                "flower": item.get("flower", ""),
                "url": ("https://fiftyflowers.com/products/" + product["handle"]) if is_collection(item["url"]) and product.get("handle") else item["url"],
                "asOf": today,
            }
            if item.get("stemsPerPiece"):
                prices[flower_id]["estimate"] = item.get("note", "")
            per_bunch = stems_per_bunch(product) or item.get("stemsPerBunch")
            if per_bunch:
                prices[flower_id]["stemsPerBunch"] = per_bunch
            print("ok    %-5s %-34s $%.2f a stem" % (flower_id, item.get("flower", "")[:34], prices[flower_id]["perStem"]))
        except Exception as err:
            failed.append(flower_id)
            # keep last month's price rather than lose it, but only if it was for this same product
            if flower_id in previous and previous[flower_id].get("url") == item["url"]:
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
        # other stores, matched by name: check the product named beside each price
        "suppliers": read_suppliers(today, catalogs),
    }
    # the searchable list of everything each store sells, for flowers added in the tool
    try:
        main_site = config.get("site", "https://fiftyflowers.com")
        catalogs[result["source"]] = {"site": main_site, "products": compact_catalog(load_catalog(main_site, 60))}
    except Exception as err:
        print("\nFAIL  catalog for %s: %s" % (result["source"], err))
    if catalogs:
        with open("catalog.json", "w", encoding="utf-8") as f:
            json.dump({"app": "stem-ledger-catalog", "date": today, "stores": catalogs}, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
        print("\nWrote catalog.json: " + ", ".join("%s %d" % (n, len(c["products"])) for n, c in catalogs.items()))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True)
        f.write("\n")
    print("\nWrote %s: %d read fresh, %d kept from before or missing." % (OUTPUT_FILE, fresh, len(failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
