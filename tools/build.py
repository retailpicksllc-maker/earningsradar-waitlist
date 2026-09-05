#!/usr/bin/env python3
"""Generate static per-ticker earnings pages for search.

The app is client-rendered, so Google sees an empty shell — the site has three indexed URLs and
ranks for none of them. These pages are the opposite: the answer to "when does NVDA report" is in
the HTML before any JavaScript runs. They hydrate from the API on load so a visitor gets live
numbers, but a crawler gets a complete page either way.

Usage:  python3 build.py NVDA [MSFT ...]        # named tickers
        python3 build.py --top 735              # by market cap, scheduled reporters only
"""
import json, sys, os, re, time, html, datetime, urllib.request

API = "https://api.earningsradar.org"
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root


class FetchFailed(Exception):
    """The request did not succeed. Distinct from a successful empty answer."""


def get(path, default=None, tries=3, timeout=30):
    """Fetch, retrying transient failures, and RAISE rather than return `default` if all fail.

    The bare `except: return default` this replaces made a timeout indistinguishable from a
    company having no history, and build() reads an empty history as "not worth a page". In one
    800-ticker run that silently dropped Kimberly-Clark -- 19 reported quarters and a confirmed
    next date -- and it was logged as "skip KMB (no history)". Rebuilt on its own it produced a
    page immediately. A page vanishing from the sitemap because one HTTP call timed out is not
    something that should be inferable only by noticing a company is missing."""
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            last = e
            if attempt + 1 < tries:
                time.sleep(1.5 * (attempt + 1))
    raise FetchFailed(f"{path}: {type(last).__name__}: {last}")


def money(v):
    if v is None:
        return "—"
    v = float(v)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v/div:,.2f}{unit}"
    return f"${v:,.0f}"


def eps(v):
    return "—" if v is None else f"${float(v):,.2f}"


# /v1/profiles is 1.1MB. Fetched once, not once per ticker — the first version downloaded it
# 3,346 times, which is 3.7GB of the same file and why the build never finished.
PROFILES = {}


# The site already ships two files the ticker pages never used: a plain-English description of
# every company, and an AI recap of its last quarter. Without them a page is 176 words of mostly
# template -- MS and NVDA shared 44% of their vocabulary, which is the profile of a page Google
# crawls and declines to index. These are the only per-company PROSE we have, so they are what
# makes one page different from the next.
SITE = OUT  # in-repo: overviews.json / insights.json sit at the root
OVERVIEWS, INSIGHTS = {}, {}


def load_content():
    global OVERVIEWS, INSIGHTS
    for name, target in (("overviews.json", "OVERVIEWS"), ("insights.json", "INSIGHTS")):
        path = os.path.join(SITE, name)
        try:
            with open(path, encoding="utf-8") as fh:
                globals()[target] = json.load(fh)
        except Exception as e:
            print(f"  {name}: not loaded ({e}) - pages will fall back to the table alone")
    print(f"  loaded {len(OVERVIEWS)} overviews, {len(INSIGHTS)} insights")


def _dividend_block(sym):
    """Recent dividend history, when a company pays one.

    /v1/dividends/{sym} was already in the API off FMP and simply was not used here -- ex-date,
    amount, payment date, frequency and yield, per ticker. Adds a second table of genuinely
    per-company numbers to a page that was otherwise one prose paragraph and an earnings table.
    Silent when a company pays nothing, which is most of them by count."""
    try:
        # One try, short timeout. Dividends are a nice-to-have; the earnings table is the page.
        # At 3 tries x 30s one hanging upstream call stalls the whole build -- which is exactly
        # what happened: 1,200 tickers ground to a halt at 768 with no further output.
        d = get(f"/v1/dividends/{sym}", {}, tries=1, timeout=8) or {}
    except FetchFailed:
        return ""
    rows = [r for r in (d.get("dividends") or []) if r.get("date") and r.get("dividend")]
    if len(rows) < 2:
        return ""
    rows = rows[:6]
    y = next((r.get("yield") for r in rows if r.get("yield")), None)
    freq = next((r.get("frequency") for r in rows if r.get("frequency")), None)
    tr = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(str(r.get("date"))[:10]),
            ("$%s" % ("%.4f" % float(r["dividend"])).rstrip("0").rstrip(".")),
            html.escape(str(r.get("paymentDate") or "-")[:10]))
        for r in rows)
    lede = "%s pays a %s dividend" % (html.escape(sym), html.escape(str(freq).lower())) if freq \
        else "%s pays a dividend" % html.escape(sym)
    if y:
        try:
            lede += ", currently yielding %.2f%%" % float(y)
        except (TypeError, ValueError):
            pass
    return ("<h2>Dividend history</h2>"
            "<p style='color:var(--mu);font-size:14px;margin:0 0 10px'>%s.</p>" % lede +
            "<table><thead><tr><th>Ex-dividend date</th><th>Amount</th><th>Paid</th></tr></thead>"
            "<tbody>%s</tbody></table>" % tr)


def _overview(sym):
    v = OVERVIEWS.get(sym.upper())
    return v.strip() if isinstance(v, str) and v.strip() else None


def _insight(sym):
    """The AI recap for a ticker, if it is a recap and not stale.

    insights.json also holds `TICKER@r` variants; the plain key is the one tied to the company.
    Only `k == 'recap'` is used -- a preview written before the print would contradict the
    actual sitting in the table two inches above it."""
    v = INSIGHTS.get(sym.upper())
    if not isinstance(v, dict):
        return None
    if str(v.get("k") or "") != "recap":
        return None
    t = str(v.get("t") or "").strip()
    return (t, str(v.get("d") or "")[:10]) if len(t) > 60 else None


def load_profiles():
    global PROFILES
    try:
        PROFILES = {p["ticker"]: p for p in (get("/v1/profiles", []) or []) if p.get("ticker")}
    except FetchFailed as e:
        print(f"  profiles unavailable ({e}); names will fall back to the ticker")
    print(f"  loaded {len(PROFILES)} company profiles")


# Every one of these pages was an ORPHAN: reachable only from sitemap.xml, linked to by nothing.
# A sitemap tells Google a URL exists; a link tells it the URL matters, and orphaned pages
# routinely stall at "Discovered - currently not indexed". Alphabetical neighbours guarantee
# every page has inbound links and no island forms; the random picks stop the graph collapsing
# into one long chain. Regenerating without this would silently undo it.
_REL_CSS = ('<style>.related{margin:26px 0 0;padding-top:14px;border-top:1px solid var(--bd);'
            'font-size:13px;line-height:2.1}.related span{color:var(--mu);margin-right:8px}'
            '.related a{display:inline-block;padding:3px 9px;margin:0 5px 4px 0;border-radius:7px;'
            'background:var(--card);color:var(--tx);text-decoration:none;border:1px solid transparent}'
            '.related a:hover{border-color:var(--ac,#2F6BFF)}'
            '.related a.all{font-weight:650}</style>')


# A preferred, warrant, right or unit is not a company and must not get its own page. 81 of
# these were live -- bac-pb, bacrp, bml-pg, cof-pi -- each a thin duplicate of the common's
# page, competing with it in search and telling a reader nothing the common does not. Same
# rule the calendar applies; applying it here keeps the site and the API saying one thing.
_DERIV = re.compile(r"^[A-Z]{1,5}[.\-](P[A-Z]?|W[STI]?|R[TW]|U)$")


def is_foreign_otc(sym):
    """5-letter ...F / ...Y = an OTC foreign-ordinary or ADR spelling of a listing we already
    carry under its primary symbol. The calendar drops the ...F form unconditionally for the
    same reason. They also fail to build far more often than they succeed -- TSMWF, IDCBY,
    ACGBY, FANDY and FRCOY were all skipped for no history in the last run -- so every slot one
    occupies in a capped selection costs a real company its page. 184 of the top 800 were these."""
    t = str(sym or "").upper()
    return len(t) == 5 and t.isalpha() and t[-1] in "FY"


def is_derivative(sym):
    t = str(sym or "").upper()
    if _DERIV.match(t):
        return True
    return len(t) == 5 and t.isalpha() and t[-1] in "PRWU"


def _related_block(sym, universe):
    """Alphabetical neighbours + a deterministic sample, so no page is a dead end."""
    import random as _r
    if not universe:
        return ('<nav class="related" aria-label="Other companies">'
                '<a class="all" href="/tickers.html">All companies A\u2013Z</a></nav>')
    order = sorted({u.upper() for u in universe})
    try:
        i = order.index(sym.upper())
    except ValueError:
        order.append(sym.upper()); order.sort(); i = order.index(sym.upper())
    picks = [order[j] for d in (-3, -2, -1, 1, 2, 3)
             for j in [i + d] if 0 <= j < len(order) and order[j] != sym.upper()]
    pool = [x for x in order if x != sym.upper() and x not in picks]
    picks += _r.Random(11 + i).sample(pool, min(4, len(pool)))
    li = "".join(f'<a href="/t/{t.lower()}.html">{t}</a>' for t in picks)
    return (_REL_CSS + '<nav class="related" aria-label="Other companies">'
            '<span>Other companies:</span>' + li +
            '<a class="all" href="/tickers.html">All companies A\u2013Z</a></nav>')


def build(sym, universe=None):
    sym = sym.upper()
    try:
        hist = get(f"/v1/history/{sym}", {}) or {}
    except FetchFailed as e:
        raise                       # surfaced by the caller as a FETCH FAILURE, never as "no history"
    quarters = hist.get("quarters") or []
    if not quarters:
        return None
    # Refuse to publish a page that cannot answer the question it ranks for. The forward calendar
    # is capped at 60 days, so mega-caps reporting in November have no date yet — a page reading
    # "no confirmed next earnings date" with an empty table is worse than no page, and thin pages
    # published at scale are what gets a site classified as doorway pages.
    if not [q for q in quarters if str(q["report_date"])[:10] >= datetime.date.today().isoformat()]:
        return None
    # A next date alone is not a page. 74 tickers — mostly foreign OTC listings — had a scheduled
    # date and an empty history table, which is thin content dressed as a real page. Require a
    # track record too, so every published page can answer both "when" and "do they usually beat".
    if len([q for q in quarters if str(q["report_date"])[:10] < datetime.date.today().isoformat()
            and q.get("eps_act") is not None]) < 4:
        return None
    name = (PROFILES.get(sym) or {}).get("name") or sym
    today = datetime.date.today().isoformat()

    upcoming = [q for q in quarters if str(q["report_date"])[:10] >= today]
    nxt = min(upcoming, key=lambda q: str(q["report_date"])) if upcoming else None
    past = [q for q in quarters if str(q["report_date"])[:10] < today
            and q.get("eps_act") is not None][:8]

    if nxt:
        d = datetime.date.fromisoformat(str(nxt["report_date"])[:10])
        when = d.strftime("%A, %B %-d, %Y")
        sess = {"bmo": "before the open", "amc": "after the close"}.get(
            (nxt.get("report_time") or "").lower(), "after the close")
        clock = nxt.get("expected_time") or ""
        lede = f"{name} ({sym}) is expected to report earnings on {when}, {sess}."
        if clock:
            lede += f" Estimated release time {clock}."
        if nxt.get("eps_est") is not None:
            lede += f" Consensus EPS estimate is {eps(nxt['eps_est'])}."
    else:
        when = "not yet scheduled"
        lede = f"{name} ({sym}) has no confirmed next earnings date."

    # The surprise comes from the API, which withholds it when the actual and estimate are on
    # different bases (a GAAP number beside a non-GAAP consensus). This page used to compute its
    # own from raw est/act and printed "$7.04 +43.4%" for Dell on a quarter the API correctly
    # refused to score. A beat is only a beat when the API says so; otherwise show the two facts
    # and no claim -- the same rule the calendar follows.
    def _sp(q):
        return q.get("surprise_eps_pct")
    scored = [q for q in past if _sp(q) is not None]
    beats = sum(1 for q in scored if float(_sp(q)) >= 0)
    # No scored quarters (every actual on an unscored basis) -> say nothing rather than
    # "0 of its last 0", which reads as a broken page.
    streak_html = ('<p style="margin-top:14px;color:var(--mu);font-size:14px">'
                   f'{html.escape(sym)} has beaten consensus EPS in <strong>{beats} of its last '
                   f'{len(scored)}</strong> scored quarters.</p>') if scored else ""
    rows = "".join(
        "<tr><td>{d}</td><td>{fq}</td><td>{ee}</td><td>{ea}</td>"
        "<td class='{cls}'>{sp}</td><td>{rv}</td></tr>".format(
            d=str(q["report_date"])[:10],
            fq=f"FY{q.get('fiscal_year','')} {q.get('fiscal_quarter','')}".strip(),
            ee=eps(q.get("eps_est")), ea=eps(q.get("eps_act")),
            cls=("" if _sp(q) is None else ("beat" if float(_sp(q)) >= 0 else "miss")),
            sp=("—" if _sp(q) is None else f"{float(_sp(q)):+.1f}%"),
            rv=money(q.get("rev_act")))
        for q in past)

    title = f"{sym} Earnings Date & History — {name} | Earnings Radar"
    desc = (f"{name} ({sym}) next earnings date: {when}. "
            f"Full EPS and revenue history, consensus estimates, and the earnings call "
            f"transcript — free, no signup.")[:300]

    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{
        "@type": "Question", "name": f"When does {name} ({sym}) report earnings?",
        "acceptedAnswer": {"@type": "Answer", "text": lede}}]}
    if scored:
        ld["mainEntity"].append({
            "@type": "Question", "name": f"Does {sym} usually beat earnings estimates?",
            "acceptedAnswer": {"@type": "Answer", "text":
                f"{sym} has beaten consensus EPS in {beats} of its last {len(scored)} scored quarters."}})

    # Per-company prose. This is what stops 668 pages being one page with the numbers swapped.
    ov = _overview(sym)
    overview_html = (f'<p class="overview">{html.escape(ov)}</p>' if ov else "")
    ins = _insight(sym)
    if ins:
        txt, when_i = ins
        stamp = f' <span class="asof">as of {html.escape(when_i)}</span>' if when_i else ""
        insight_html = (f'<h2>What happened last quarter{stamp}</h2>'
                        f'<p class="insight">{html.escape(txt)}</p>')
    else:
        insight_html = ""
    # BreadcrumbList: the second schema type the brief asked for, and the one that can earn a
    # breadcrumb trail in the result instead of a bare URL.
    crumbs = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Earnings Radar",
             "item": "https://earningsradar.org/"},
            {"@type": "ListItem", "position": 2, "name": "All companies",
             "item": "https://earningsradar.org/tickers.html"},
            {"@type": "ListItem", "position": 3, "name": f"{name} ({sym}) earnings",
             "item": f"https://earningsradar.org/t/{sym.lower()}.html"}]}, separators=(",", ":"))
    crumbs_html = f'<script type="application/ld+json">{crumbs}</script>'
    dividends_html = _dividend_block(sym)
    related = _related_block(sym, universe)
    doc = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="https://earningsradar.org/t/{sym.lower()}.html">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="https://earningsradar.org/t/{sym.lower()}.html">
<meta property="og:image" content="https://earningsradar.org/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<script type="application/ld+json">{json.dumps(ld)}</script>
<style>
 :root{{--bg:#0A1024;--card:rgba(255,255,255,.05);--bd:rgba(255,255,255,.10);
        --tx:#ECECF1;--mu:#9AA4C2;--bl:#2F6BFF;--gr:#34D399;--rd:#F87171}}
 *{{box-sizing:border-box;margin:0}}
 body{{background:var(--bg);color:var(--tx);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 .wrap{{max-width:820px;margin:0 auto;padding:28px 20px 70px}}
 a{{color:var(--bl);text-decoration:none}}
 header{{display:flex;align-items:center;gap:10px;margin-bottom:30px}}
 header b{{font-weight:800;font-size:19px}} header b i{{color:#6BA5FF;font-style:normal}}
 h1{{font-size:clamp(25px,4vw,34px);font-weight:800;letter-spacing:-.5px;margin-bottom:10px}}
 .lede{{font-size:18px;color:var(--tx);margin-bottom:24px}}
 .next{{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:18px 20px;margin-bottom:26px}}
 .next .k{{color:var(--mu);font-size:13px;text-transform:uppercase;letter-spacing:.5px}}
 .next .v{{font-size:23px;font-weight:700;margin-top:3px}}
 h2{{font-size:20px;margin:30px 0 12px;font-weight:700}}
 table{{width:100%;border-collapse:collapse;font-size:14.5px}}
 th,td{{text-align:right;padding:9px 8px;border-bottom:1px solid var(--bd);white-space:nowrap}}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
 th{{color:var(--mu);font-weight:600;font-size:12.5px;text-transform:uppercase}}
 .beat{{color:var(--gr)}} .miss{{color:var(--rd)}}
 .overview{{font-size:16px;line-height:1.6;color:var(--tx);margin:6px 0 14px;max-width:66ch}}
 .insight{{font-size:15px;line-height:1.65;color:var(--tx);margin:6px 0 0;max-width:70ch}}
 .asof{{font-size:12.5px;color:var(--mu);font-weight:500;text-transform:none;letter-spacing:0}}
 .cta{{display:inline-block;background:var(--bl);color:#fff;padding:11px 20px;border-radius:11px;font-weight:700;margin-top:22px}}
 footer{{margin-top:44px;color:var(--mu);font-size:13px;border-top:1px solid var(--bd);padding-top:16px}}
</style></head><body><div class="wrap">
<header><svg width="22" height="27" viewBox="0 0 120 150"><path d="M60 6 C2 42 2 108 60 144 Z" fill="#9FC0FF"/><path d="M60 6 C118 42 118 108 60 144 Z" fill="#2F6BFF"/></svg>
<b><a href="/">earnings<i>radar</i></a></b></header>
<h1>{html.escape(sym)} Earnings Date &amp; History</h1>
{overview_html}
<p class="lede">{html.escape(lede)}</p>
<div class="next"><div class="k">Next earnings date</div><div class="v" id="nextdate">{html.escape(when)}</div></div>
<h2>Recent earnings history</h2>
<table><thead><tr><th>Report date</th><th>Quarter</th><th>EPS est.</th><th>EPS actual</th><th>Surprise</th><th>Revenue</th></tr></thead>
<tbody>{rows or '<tr><td colspan="6">No reported quarters yet.</td></tr>'}</tbody></table>
{streak_html}
{insight_html}
{dividends_html}
{crumbs_html}
<a class="cta" href="/app.html#{html.escape(sym)}">See {html.escape(sym)} on the live calendar →</a>
<script>
// These pages are static, and the data behind them is not: the ingest revises report dates daily,
// and two of the first five I checked had moved by a day between generation and publication. A
// crawler gets the rendered HTML above; a visitor gets the live figure. Without this, a page whose
// entire job is stating a date would confidently state yesterday's answer.
(async function(){{
  try{{
    const r = await fetch("https://api.earningsradar.org/v1/history/{sym}", {{cache:"no-store"}});
    if(!r.ok) return;
    const q = (await r.json()).quarters || [];
    const today = new Date().toISOString().slice(0,10);
    const next = q.filter(x => String(x.report_date).slice(0,10) >= today)
                  .sort((a,b) => String(a.report_date).localeCompare(String(b.report_date)))[0];
    if(!next) return;
    const d = new Date(String(next.report_date).slice(0,10) + "T12:00:00Z");
    const txt = d.toLocaleDateString("en-US",
      {{weekday:"long", month:"long", day:"numeric", year:"numeric", timeZone:"UTC"}});
    const el = document.getElementById("nextdate");
    if(el && el.textContent.trim() !== txt){{ el.textContent = txt; }}
  }}catch(e){{}}
}})();
</script>
<div style="display:flex;justify-content:center;padding:10px 20px 0"><a href="https://x.com/_EarningsRadar" target="_blank" rel="noopener me" aria-label="Follow Earnings Radar on X" style="display:inline-flex;align-items:center;gap:10px;padding:11px 20px;border-radius:999px;border:1px solid var(--bd);background:var(--card);color:var(--tx);font-weight:650;font-size:14.5px;text-decoration:none"><svg viewBox="0 0 24 24" aria-hidden="true" style="width:16px;height:16px;fill:currentColor;flex:none"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span>Follow us on X</span><span style="color:var(--mu);font-weight:500">@_EarningsRadar</span></a></div>
{related}
<footer>Data updated {today}. Estimates and actuals are non-GAAP where the company reports them.
Informational only — not investment advice. &copy; 2026 Earnings Radar ·
<a href="/">Home</a> · <a href="/app.html">Earnings calendar</a></footer>
</div></body></html>"""
    return doc


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--top":
        n = int(args[1]) if len(args) > 1 else 735
        uni = get("/v1/universe?limit=20000", []) or []
        rows = uni if isinstance(uni, list) else uni.get("rows", [])
        syms = [r["ticker"] for r in sorted(
            (r for r in rows if r.get("next_report_date")
             and not is_derivative(r.get("ticker"))
             and not is_foreign_otc(r.get("ticker"))),
            key=lambda r: -(r.get("market_cap_musd") or 0))[:n]]
    else:
        syms = args or ["NVDA"]
    load_profiles()
    load_content()
    made = 0
    failed = []
    for s in syms:
        if is_derivative(s):
            print(f"  skip {s} (preferred/warrant, not a company)"); continue
        try:
            doc = build(s, universe=syms)
        except FetchFailed as e:
            failed.append(s)
            print(f"  FETCH FAILURE {s}: {e}"); continue
        if not doc:
            print(f"  skip {s} (no history)"); continue
        d = os.path.join(OUT, "t"); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, s.lower() + ".html"), "w", encoding="utf-8").write(doc)
        made += 1
        if made <= 3 or made % 100 == 0:
            print(f"  {made}: t/{s.lower()}.html  {len(doc):,} bytes", flush=True)
    print(f"\n{made} page(s)")
    if failed:
        print(f"{len(failed)} FETCH FAILURE(S) -- these are NOT companies without data, they are "
              f"pages that would silently vanish from the sitemap. Re-run them:")
        print("  python3 build.py " + " ".join(failed))
