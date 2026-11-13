import json, sys, urllib.request
UA = "StemLedgerPriceCheck/1.0 (monthly personal price check)"
for d in sys.argv[1:]:
    for host in (d, "www." + d):
        try:
            req = urllib.request.Request("https://%s/products.json?limit=4" % host, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            ps = data.get("products", [])
            print("OK   %-28s %d | %s" % (host, len(ps), " || ".join("%s :: %s" % (p.get("title"), " / ".join("%s $%s" % (v.get("title"), v.get("price")) for v in p.get("variants", [])[:3])) for p in ps[:3])[:420]))
            break
        except Exception as e:
            print("FAIL %-28s %s" % (host, str(e)[:80]))
