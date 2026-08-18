"""
Fixture site with DELIBERATELY PLANTED defects.
Ground truth is recorded in fixture/GROUND_TRUTH.json so detection accuracy
can be measured exactly — better validation than a live site where the true
defect count is unknown.
"""
import json, os, pathlib
D = pathlib.Path("fixture/site"); D.mkdir(parents=True, exist_ok=True)

GT = {}

def page(path, title=None, desc=None, h1s=None, body="", extra_head="",
         imgs=0, imgs_noalt=0, viewport=True, charset=True, doctype=True,
         canonical=None, schema=None, scripts="", words=300, lang=True,
         headings_skip=False):
    h = []
    if doctype: h.append("<!DOCTYPE html>")
    langattr = ' lang="en-US"' if lang else ''
    h.append('<html' + langattr + '><head>')
    if charset: h.append('<meta charset="utf-8">')
    if viewport: h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    if title: h.append(f"<title>{title}</title>")
    if desc: h.append(f'<meta name="description" content="{desc}">')
    if canonical: h.append(f'<link rel="canonical" href="{canonical}">')
    if schema: h.append(f'<script type="application/ld+json">{json.dumps(schema)}</script>')
    h.append(extra_head); h.append("</head><body>")
    h.append('<nav><a href="/">Home</a> <a href="/living-room/">Living Room</a> '
             '<a href="/bedroom/">Bedroom</a> <a href="/mattresses/">Mattresses</a> '
             '<a href="/about/">About</a> <a href="/contact/">Contact</a> '
             '<a href="/privacy/">Privacy</a></nav>')
    for t in (h1s or []): h.append(f"<h1>{t}</h1>")
    if headings_skip: h.append("<h4>Skipped straight to H4</h4>")
    else: h.append("<h2>Overview</h2>")
    h.append(f"<p>{body} {'furniture quality comfort value delivery ' * (words//5)}</p>")
    for i in range(imgs):
        alt = "" if i < imgs_noalt else f'alt="Product photo {i}"'
        h.append(f'<img src="/img/IMG_{1000+i}.jpg" {alt}>')
    h.append(scripts)
    h.append('<footer><a href="/broken-page/">Deals</a> <a href="/terms/">Terms</a></footer>')
    h.append("</body></html>")
    p = D / path.strip("/") / "index.html" if path != "/" else D / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(h))

ORG = {"@context":"https://schema.org","@type":"Organization","name":"Grand Home Furnishings",
       "url":"http://localhost:8099/"}
BC  = {"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}

TRACK = ('<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC1234"></script>'
         '<script>window.dataLayer=window.dataLayer||[];</script>'
         '<script src="https://www.googletagmanager.com/gtag/js?id=G-ABCD123456"></script>'
         '<script src="https://www.clarity.ms/tag/xyz"></script>')

# --- homepage: clean-ish
page("/", "Grand Home Furnishings | Furniture & Mattresses in VA, WV, TN",
     "Shop quality furniture and mattresses across 18 stores. Free delivery available.",
     ["Grand Home Furnishings"], "Welcome.", imgs=6, imgs_noalt=2,
     canonical="http://localhost:8099/", schema=[ORG, BC], scripts=TRACK, words=400)

# --- DEFECT: duplicate titles (3 pages share one title)
for slug in ("living-room", "bedroom", "dining-room"):
    page(f"/{slug}/", "Furniture | Grand Home Furnishings",
         "Shop our range of quality home furniture with free delivery available today.",
         [f"{slug.replace('-',' ').title()}"], f"Browse {slug}.", imgs=8, imgs_noalt=5,
         canonical=f"http://localhost:8099/{slug}/", scripts=TRACK, words=250)

# --- DEFECT: multiple H1s (2 pages)
page("/mattresses/", "Mattresses | Grand Home Furnishings",
     "Find the perfect mattress with our 30-day risk-free trial and lowest price guarantee.",
     ["Mattresses", "Shop All Mattresses"], "Sleep well.", imgs=10, imgs_noalt=7,
     canonical="http://localhost:8099/mattresses/", scripts=TRACK, words=300)
page("/outdoor/", "Outdoor Furniture | Grand Home Furnishings",
     "Patio and outdoor furniture built to last through every season, with free delivery.",
     ["Outdoor", "Patio Collection"], "Outside living.", imgs=5, imgs_noalt=3,
     canonical="http://localhost:8099/outdoor/", scripts=TRACK, words=280)

# --- DEFECT: missing meta description (2 pages)
page("/kids/", "Kids Furniture | Grand Home Furnishings", None, ["Kids Furniture"],
     "For children.", imgs=4, imgs_noalt=2, canonical="http://localhost:8099/kids/",
     scripts=TRACK, words=220)
page("/decor/", "Decor | Grand Home Furnishings", None, ["Decor"], "Accents.",
     imgs=6, imgs_noalt=1, canonical="http://localhost:8099/decor/", scripts=TRACK, words=210)

# --- DEFECT: no H1 + thin content
page("/home-office/", "Home Office Furniture | Grand Home Furnishings",
     "Desks, chairs and storage for a productive home office setup at every budget.",
     [], "Short.", imgs=2, imgs_noalt=0, canonical="http://localhost:8099/home-office/",
     scripts=TRACK, words=20)

# --- DEFECT: no viewport, no charset, no doctype, no lang, heading skip
page("/sale/", "Sale | Grand Home Furnishings",
     "Clearance furniture and mattress deals updated weekly across all our store locations.",
     ["Sale"], "Deals.", imgs=3, imgs_noalt=3, viewport=False, charset=False,
     doctype=False, lang=False, headings_skip=True,
     canonical="http://localhost:8099/sale/", scripts=TRACK, words=180)

# --- DEFECT: underscore + uppercase URL, missing canonical, title too long
page("/Store_Locations/", 
     "All Of Our Grand Home Furnishings Store Locations Across Virginia West Virginia And Tennessee",
     "Find your nearest Grand Home Furnishings store across Virginia, West Virginia and Tennessee.",
     ["Store Locations"], "18 stores.", imgs=1, imgs_noalt=0, scripts=TRACK, words=240)

# --- trust pages
for slug, t in (("about","About Us | Grand Home Furnishings"),
                ("contact","Contact Us | Grand Home Furnishings"),
                ("privacy","Privacy Policy | Grand Home Furnishings"),
                ("terms","Terms & Conditions | Grand Home Furnishings")):
    page(f"/{slug}/", t,
         f"Read our {slug} information covering policies, service standards and store details.",
         [t.split(" | ")[0]], f"{slug} content.", imgs=1,
         canonical=f"http://localhost:8099/{slug}/", scripts=TRACK, words=260)

# --- ORPHAN page (in sitemap, not linked from anywhere)
page("/clearance-warehouse/", "Clearance Warehouse | Grand Home Furnishings",
     "Warehouse clearance stock available for immediate collection at unbeatable prices.",
     ["Clearance Warehouse"], "Orphan.", imgs=2, canonical="http://localhost:8099/clearance-warehouse/",
     scripts=TRACK, words=230)

# robots.txt — DEFECT: blocks GPTBot and ClaudeBot
(D/"robots.txt").write_text(
 "User-agent: *\nAllow: /\n\n"
 "User-agent: GPTBot\nDisallow: /\n\n"
 "User-agent: ClaudeBot\nDisallow: /\n\n"
 "Sitemap: http://localhost:8099/sitemap.xml\n")

urls = ["/","/living-room/","/bedroom/","/dining-room/","/mattresses/","/outdoor/",
        "/kids/","/decor/","/home-office/","/sale/","/Store_Locations/","/about/",
        "/contact/","/privacy/","/terms/","/clearance-warehouse/"]
(D/"sitemap.xml").write_text(
 '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
 + "\n".join(f"<url><loc>http://localhost:8099{u}</loc></url>" for u in urls)
 + "\n</urlset>\n")
# NOTE: no llms.txt written  → GEO-01 should report Not Implemented

GT = {
 "ONP-01": {"expect":"Fail","pages_affected":3,"note":"3 category pages share one title"},
 "ONP-08": {"expect":"Fail","count":2,"note":"mattresses + outdoor have 2 H1s"},
 "ONP-06": {"expect":"Fail","count":2,"note":"kids + decor missing meta description"},
 "ONP-31": {"expect":"Fail","count":1,"note":"home-office has no H1"},
 "ONP-10": {"expect":"Fail","count":1,"note":"home-office is thin (<200 words)"},
 "ONP-04": {"expect":"Fail","count":1,"note":"Store_Locations title >60 chars"},
 "MOB-01": {"expect":"Fail","count":1,"note":"sale page has no viewport"},
 "HTML-01":{"expect":"Fail","count":1,"note":"sale page has no charset"},
 "HTML-02":{"expect":"Fail","count":1,"note":"sale page has no doctype"},
 "INTL-04":{"expect":"Fail","count":1,"note":"sale page has no lang attribute"},
 "URL-09": {"expect":"Fail","count":1,"note":"/Store_Locations/ uses underscore"},
 "URL-12": {"expect":"Fail","count":1,"note":"/Store_Locations/ has uppercase"},
 "URL-18": {"expect":"Fail","count":1,"note":"Store_Locations missing canonical"},
 "TECH-02":{"expect":"Fail","min_count":1,"note":"/broken-page/ linked in every footer"},
 "TECH-06":{"expect":"Fail","min_count":1,"note":"broken internal link to /broken-page/"},
 "GEO-01": {"expect":"Not Implemented","note":"no llms.txt published"},
 "GEO-04": {"expect":"Fail","blocked":["GPTBot","ClaudeBot"],"note":"robots blocks 2 AI crawlers"},
 "GEO-10": {"expect":"Not Implemented","note":"no FAQPage schema anywhere"},
 "SCHEMA-02":{"expect":"Pass","note":"Organization schema on homepage"},
 "SCHEMA-06":{"expect":"Not Implemented","note":"no Product schema"},
 "SCHEMA-07":{"expect":"Not Implemented","note":"no FAQ schema"},
 "SCHEMA-09":{"expect":"Not Implemented","note":"no LocalBusiness schema"},
 "ANA-01": {"expect":"Pass","note":"GTM container present"},
 "ANA-02": {"expect":"Pass","note":"GA4 gtag present"},
 "ANA-04": {"expect":"Pass","note":"Clarity present"},
 "ANA-06": {"expect":"Not Implemented","note":"no Meta Pixel"},
 "ANA-10": {"expect":"Not Implemented","note":"no call tracking"},
 "ANA-12": {"expect":"Not Implemented","note":"no cookie consent"},
 "EEAT-12":{"expect":"Pass","note":"/contact/ exists"},
 "EEAT-13":{"expect":"Pass","note":"/about/ exists"},
 "EEAT-15":{"expect":"Pass","note":"/privacy/ exists"},
 "EEAT-17":{"expect":"Not Implemented","note":"no refund/return policy page"},
 "EEAT-07":{"expect":"Not Implemented","note":"no author/team pages"},
 "ONP-14": {"expect":"Fail","min_count":20,"note":"many images lack alt"},
 "TECH-25":{"expect":"Fail","min_count":1,"note":"/clearance-warehouse/ is orphaned"},
 "TECH-22":{"expect":"Pass","note":"sitemap.xml exists"},
 "TECH-23":{"expect":"Pass","note":"sitemap declared in robots.txt"},
}
pathlib.Path("fixture/GROUND_TRUTH.json").write_text(json.dumps(GT, indent=1))
print(f"fixture built: {sum(1 for _ in D.rglob('*.html'))} pages, {len(GT)} ground-truth assertions")
