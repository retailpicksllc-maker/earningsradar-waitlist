#!/usr/bin/env python3
"""After build.py and build_transcripts.py: make the three surfaces agree.

Regenerates tickers.html (the A-Z directory) and sitemap.xml from what actually exists in
t/, and injects the transcript link into each parent page that has one. Run by the nightly
workflow; the invariant it enforces is the one the audits kept checking by hand: files,
sitemap and directory must never disagree."""
import os, re, io, html, collections, datetime, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

rows = []
for f in sorted(os.listdir("t")):
    if not f.endswith(".html"):
        continue
    h = io.open("t/" + f, encoding="utf-8", errors="replace").read(4000)
    m = re.search(r'<title>\s*([A-Z0-9.\-]+)\s+Earnings Date[^—]*—\s*(.*?)\s*\|', h)
    rows.append((m.group(1), html.unescape(m.group(2)).strip(), f) if m
                else (os.path.splitext(f)[0].upper(), "", f))
rows.sort(key=lambda r: r[0])
tr_dirs = sorted(d for d in os.listdir("t") if os.path.isdir(os.path.join("t", d))
                 and os.path.exists(os.path.join("t", d, "transcript.html")))

# ---- directory ----------------------------------------------------------------
g = collections.OrderedDict()
for t, n, f in rows:
    g.setdefault(t[0] if t[0].isalpha() else "#", []).append((t, n, f))
def e(x): return html.escape(x, quote=True)
sec = "".join('<section id="L%s"><h2>%s</h2><ul class="grid">%s</ul></section>' % (L, L,
      "".join('<li><a href="/t/%s"><b>%s</b><span>%s</span></a></li>' % (f, e(t), e(n))
              for t, n, f in it)) for L, it in g.items())
nav = "".join('<a href="#L%s">%s</a>' % (L, L) for L in g)
src = io.open("tickers.html", encoding="utf-8").read()
src = re.sub(r'<nav class="az">.*?(?=<footer>)',
             '<nav class="az">%s</nav>\n%s\n' % (nav, sec), src, flags=re.S)
src = re.sub(r'\b\d[\d,]* US-listed tickers', '%d US-listed tickers' % len(rows), src)
io.open("tickers.html", "w", encoding="utf-8").write(src)

# ---- transcript links on parents ----------------------------------------------
linked = 0
for d in tr_dirs:
    p = os.path.join("t", d + ".html")
    if not os.path.exists(p):
        continue
    h = io.open(p, encoding="utf-8").read()
    if "/transcript.html" in h:
        continue
    m = re.search(r'<nav class="related"', h)
    if not m:
        continue
    block = ('<p style="margin:18px 0 0"><a class="cta" href="/t/%s/transcript.html">'
             'Read the %s earnings call summary →</a></p>\n' % (d, d.upper()))
    io.open(p, "w", encoding="utf-8").write(h[:m.start()] + block + h[m.start():])
    linked += 1

# ---- sitemap -------------------------------------------------------------------
today = datetime.date.today().isoformat()
top = [("https://earningsradar.org/", "1.0"),
       ("https://earningsradar.org/tickers.html", "0.9"),
       ("https://earningsradar.org/app.html", "0.9"),
       ("https://earningsradar.org/privacy.html", "0.4")]
body = "".join('<url><loc>%s</loc><lastmod>%s</lastmod><changefreq>daily</changefreq>'
               '<priority>%s</priority></url>' % (u, today, p) for u, p in top)
body += "".join('<url><loc>https://earningsradar.org/t/%s</loc><lastmod>%s</lastmod>'
                '<changefreq>weekly</changefreq><priority>0.7</priority></url>'
                % (f, today) for _, _, f in rows)
body += "".join('<url><loc>https://earningsradar.org/t/%s/transcript.html</loc>'
                '<lastmod>%s</lastmod><changefreq>weekly</changefreq><priority>0.8</priority></url>'
                % (d, today) for d in tr_dirs)
io.open("sitemap.xml", "w", encoding="utf-8").write(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + '</urlset>\n')

n_sm = len(top) + len(rows) + len(tr_dirs)
print("postbuild: %d pages, %d transcripts, %d parent links added, sitemap %d URLs"
      % (len(rows), len(tr_dirs), linked, n_sm))
# hard invariant: bail nonzero if surfaces disagree, so the workflow refuses to commit
s = io.open("sitemap.xml", encoding="utf-8").read()
tk = io.open("tickers.html", encoding="utf-8").read()
assert len(set(re.findall(r'/t/([a-z0-9.\-]+\.html)</loc>', s))) == len(rows), "sitemap != files"
assert len(set(re.findall(r'href="/t/([a-z0-9.\-]+\.html)"', tk))) == len(rows), "directory != files"
