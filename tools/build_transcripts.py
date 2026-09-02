#!/usr/bin/env python3
"""Lever 2 - transcript SUMMARY pages at /t/{ticker}/transcript.html

Deliberately NOT the raw transcript. The verbatim text is syndicated across Motley Fool,
Seeking Alpha and Insider Monkey, so a raw-transcript page is duplicate content Google will
not rank -- and ours is a licensed Alpha Vantage feed, which makes wholesale republication a
licensing question as well as a pointless one. What ranks is original: a written summary,
short attributed quotes, and an AI take. Both reasons point the same way.
"""
import json, sys, os, re, time, html, datetime, urllib.request

API = "https://api.earningsradar.org"
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
SITE = OUT  # in-repo: overviews.json / insights.json sit at the root
OVERVIEWS, INSIGHTS, PROFILES = {}, {}, {}


class FetchFailed(Exception):
    pass


def get(path, tries=3, timeout=25):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            last = e
            if i + 1 < tries:
                time.sleep(1.2 * (i + 1))
    raise FetchFailed(f"{path}: {type(last).__name__}: {last}")


def load_content():
    global OVERVIEWS, INSIGHTS, PROFILES
    for name, tgt in (("overviews.json", "OVERVIEWS"), ("insights.json", "INSIGHTS")):
        try:
            with open(os.path.join(SITE, name), encoding="utf-8") as fh:
                globals()[tgt] = json.load(fh)
        except Exception as e:
            print(f"  {name}: {e}")
    try:
        PROFILES = {p["ticker"]: p for p in (get("/v1/profiles") or []) if p.get("ticker")}
    except FetchFailed as e:
        print(f"  profiles: {e}")
    print(f"  loaded {len(OVERVIEWS)} overviews, {len(INSIGHTS)} insights, {len(PROFILES)} profiles")


def eps(v):
    return "—" if v is None else f"${float(v):,.2f}"


def money(v):
    if v is None:
        return "—"
    v = float(v)
    for u, d in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= d:
            return f"${v/d:,.2f}{u}"
    return f"${v:,.0f}"


# Operator boilerplate and safe-harbour language carry no information and would pad every page
# with the same words -- the exact near-duplicate problem this page type exists to avoid.
_SKIP = re.compile(r"conference operator|welcome everyone|question-and-answer session|"
                   r"forward-looking statements|safe harbor|replay of this call|"
                   r"star (one|1)|press star|turn the call over|thank you.{0,25}operator", re.I)
# A quote earns its place by carrying a number or a forward-looking claim.
_SUBSTANCE = re.compile(r"\b\d|\bpercent\b|\bmargin|\bguidance|\bdemand|\bgrowth|\brevenue|"
                        r"\bbacklog|\bcapacity|\bpricing|\bexpect|\boutlook|\brecord\b", re.I)


def _quotes(segments, want=5):
    """Short, attributed, substantive excerpts. Short is the point: quotation, not reproduction."""
    out = []
    for s in segments:
        txt = re.sub(r"\s+", " ", str(s.get("text") or "")).strip()
        if len(txt) < 80 or _SKIP.search(txt):
            continue
        spk = str(s.get("speaker") or "").strip()
        title = str(s.get("title") or "").strip()
        if spk.lower() in ("operator", ""):
            if not title:
                continue
        # first substantive sentence, capped hard
        for sent in re.split(r"(?<=[.!?])\s+", txt):
            sent = sent.strip()
            if 60 <= len(sent) <= 240 and _SUBSTANCE.search(sent):
                who = title or spk
                out.append((who, sent))
                break
        if len(out) >= want:
            break
    return out


def build(sym):
    sym = sym.upper()
    tr = get(f"/v1/transcript/{sym}")
    segs = tr.get("segments") or []
    if not segs:
        return None, "no transcript segments"
    quotes = _quotes(segs)
    if len(quotes) < 3:
        return None, f"only {len(quotes)} usable quotes"

    hist = get(f"/v1/history/{sym}")
    quarters = hist.get("quarters") or []
    today = datetime.date.today().isoformat()
    past = [q for q in quarters if str(q.get("report_date"))[:10] < today
            and q.get("eps_act") is not None]
    if not past:
        return None, "no reported quarter"
    q0 = past[0]
    name = (PROFILES.get(sym) or {}).get("name") or sym
    fy, fq = q0.get("fiscal_year"), str(q0.get("fiscal_quarter") or "").upper()
    label = f"{fq} FY{str(fy)[-2:]}" if fy and fq else "the latest quarter"
    rd = str(q0.get("report_date"))[:10]
    try:
        rd_h = datetime.date.fromisoformat(rd).strftime("%B %-d, %Y")
    except ValueError:
        rd_h = rd

    ee, ea = q0.get("eps_est"), q0.get("eps_act")
    re_, ra = q0.get("rev_est"), q0.get("rev_act")
    beat = (ee is not None and ea is not None and float(ea) >= float(ee))
    verb = "beat" if beat else "missed"
    streak = sum(1 for q in past[:8] if q.get("eps_est") and q.get("eps_act") is not None
                 and float(q["eps_act"]) >= float(q["eps_est"]))
    n = min(len(past), 8)

    # TL;DR: written from the numbers, not lifted from the call.
    tldr = [f"{name} ({sym}) reported {label} results on {rd_h}."]
    if ee is not None and ea is not None:
        tldr.append(f"Earnings per share came in at {eps(ea)} against a {eps(ee)} consensus, "
                    f"so the company {verb} on the bottom line.")
    if re_ is not None and ra is not None:
        rbeat = "above" if float(ra) >= float(re_) else "below"
        tldr.append(f"Revenue of {money(ra)} landed {rbeat} the {money(re_)} estimate.")
    tldr.append(f"{sym} has beaten consensus EPS in {streak} of its last {n} reported quarters.")
    tldr.append("Highlights from management's remarks on the call are below.")

    ov = OVERVIEWS.get(sym)
    ov_html = f'<p class="overview">{html.escape(ov.strip())}</p>' if isinstance(ov, str) and ov.strip() else ""
    ins = INSIGHTS.get(sym)
    ins_html = ""
    if isinstance(ins, dict) and str(ins.get("k") or "") == "recap" and len(str(ins.get("t") or "")) > 60:
        ins_html = ('<h2>What moved the stock</h2>'
                    f'<p class="insight">{html.escape(str(ins["t"]).strip())}</p>')

    bullets = "".join(
        f'<li><b>{html.escape(who)}:</b> &ldquo;{html.escape(sent)}&rdquo;</li>'
        for who, sent in quotes)

    facts = (f"<tr><td>Report date</td><td>{html.escape(rd_h)}</td></tr>"
             f"<tr><td>EPS actual vs estimate</td><td>{eps(ea)} vs {eps(ee)}</td></tr>"
             f"<tr><td>Revenue actual vs estimate</td><td>{money(ra)} vs {money(re_)}</td></tr>"
             f"<tr><td>Beat rate (last {n})</td><td>{streak} of {n}</td></tr>")

    title = f"{name} ({sym}) Earnings Call Transcript &amp; Summary — {label} | Earnings Radar"
    desc = (f"{name} ({sym}) {label} earnings call summary: key quotes from management, "
            f"EPS of {eps(ea)} versus a {eps(ee)} estimate, and what moved the stock.")[:300]
    url = f"https://earningsradar.org/t/{sym.lower()}/transcript.html"

    crumbs = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Earnings Radar", "item": "https://earningsradar.org/"},
            {"@type": "ListItem", "position": 2, "name": f"{sym} earnings",
             "item": f"https://earningsradar.org/t/{sym.lower()}.html"},
            {"@type": "ListItem", "position": 3, "name": f"{label} call summary", "item": url}]},
        separators=(",", ":"))
    faq = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": f"What did {name} say on its {label} earnings call?",
         "acceptedAnswer": {"@type": "Answer", "text": " ".join(tldr)}},
        {"@type": "Question", "name": f"Did {sym} beat earnings in {label}?",
         "acceptedAnswer": {"@type": "Answer",
            "text": f"{name} {verb} consensus EPS in {label}, reporting {eps(ea)} against "
                    f"a {eps(ee)} estimate on {rd_h}."}}]}, separators=(",", ":"))

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="canonical" href="{url}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<meta name="description" content="{html.escape(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(f'{name} ({sym}) Earnings Call Summary — {label}')}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:image" content="https://earningsradar.org/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@_EarningsRadar">
<link rel="icon" href="/favicon.ico" sizes="any">
<meta name="theme-color" content="#0A1024">
<style>
:root{{--bg:#0A1024;--bg2:#0d1430;--card:rgba(255,255,255,.045);--bd:rgba(255,255,255,.09);
--bl:#2F6BFF;--tx:#ECECF1;--mu:#94A0BF}}
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(180deg,var(--bg),var(--bg2));color:var(--tx);
font:15.5px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:760px;margin:0 auto;padding:0 18px 50px}}
header{{padding:24px 0 4px}} header a{{color:var(--tx);text-decoration:none;font-weight:700}}
nav.bc{{font-size:13px;color:var(--mu);margin:10px 0 6px}} nav.bc a{{color:var(--mu)}}
h1{{font-size:25px;line-height:1.25;margin:10px 0 12px}}
h2{{font-size:19px;margin:28px 0 10px}}
.overview{{color:var(--mu);margin:0 0 16px}}
ul.hl{{list-style:none;padding:0;margin:0}}
ul.hl li{{background:var(--card);border:1px solid var(--bd);border-radius:10px;
padding:11px 13px;margin:0 0 9px}}
ul.hl b{{color:var(--bl)}}
table{{width:100%;border-collapse:collapse;font-size:14.5px;margin-top:6px}}
td{{padding:8px;border-bottom:1px solid var(--bd)}} td:last-child{{text-align:right}}
.insight{{margin:0}}
.rel{{margin-top:26px;padding-top:14px;border-top:1px solid var(--bd);font-size:13.5px;line-height:2.1}}
.rel a{{display:inline-block;padding:3px 9px;margin:0 5px 4px 0;border-radius:7px;
background:var(--card);color:var(--tx);text-decoration:none;border:1px solid transparent}}
.rel a:hover{{border-color:var(--bl)}}
footer{{margin-top:36px;color:var(--mu);font-size:13px;border-top:1px solid var(--bd);padding-top:15px}}
footer a{{color:var(--mu)}}
</style></head><body><div class="wrap">
<header><a href="/">earnings radar</a></header>
<nav class="bc"><a href="/">Home</a> › <a href="/t/{sym.lower()}.html">{html.escape(sym)}</a> › Transcript</nav>
<h1>{html.escape(name)} ({html.escape(sym)}) Earnings Call Summary — {html.escape(label)}</h1>
{ov_html}
<p>{' '.join(html.escape(t) for t in tldr)}</p>
<h2>Key highlights from the call</h2>
<ul class="hl">{bullets}</ul>
{ins_html}
<h2>Quick facts</h2>
<table><tbody>{facts}</tbody></table>
<div class="rel"><a href="/t/{sym.lower()}.html">← {html.escape(sym)} earnings date &amp; history</a>
<a href="/tickers.html">All companies A–Z</a></div>
<script type="application/ld+json">{crumbs}</script>
<script type="application/ld+json">{faq}</script>
<footer>Summary and selected quotations from {html.escape(name)}'s {html.escape(label)} earnings
call, published {datetime.date.today().isoformat()}. Excerpts are quoted for commentary;
full transcripts remain with their publishers. Informational only — not investment advice.
&copy; 2026 Earnings Radar · <a href="/">Home</a> · <a href="/app.html">Earnings calendar</a></footer>
</div></body></html>"""
    return doc, None


if __name__ == "__main__":
    syms = [a.upper() for a in sys.argv[1:]] or ["NVDA"]
    load_content()
    made, skipped, failed = 0, [], []
    for s in syms:
        try:
            doc, why = build(s)
        except FetchFailed as e:
            failed.append(s); print(f"  FETCH FAILURE {s}: {e}", flush=True); continue
        if not doc:
            skipped.append((s, why)); print(f"  skip {s} ({why})", flush=True); continue
        d = os.path.join(OUT, "t", s.lower())
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "transcript.html"), "w", encoding="utf-8") as fh:
            fh.write(doc)
        made += 1
        print(f"  {made}: t/{s.lower()}/transcript.html  {len(doc):,} bytes", flush=True)
    print(f"\n{made} page(s), {len(skipped)} skipped, {len(failed)} fetch failures")
    if failed:
        print("  re-run: python3 build_transcripts.py " + " ".join(failed))
