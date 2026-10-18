from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from typing import List, Tuple, Optional

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:
    sync_playwright = None  # type: ignore

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_BASE = "https://en.wikipedia.org/wiki/"


def _abs(p: str) -> str:
    return os.path.abspath(p)


def _safe_slug(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:140] or "untitled"


# ------------------------------
# Search helpers
# ------------------------------
def _quote_for_search(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'

MATH_MAP = {
    "∫": [r"\\int"],
    "∮": [r"\\oint"],
    "∑": [r"\\sum"],
    "∏": [r"\\prod"],
    "√": [r"\\sqrt"],
    "∞": [r"\\infty"],
    "≈": [r"\\approx"],
    "≃": [r"\\simeq"],
    "≅": [r"\\cong"],
    "≤": [r"\\le", r"\\leq"],
    "≥": [r"\\ge", r"\\geq"],
    "→": [r"\\to", r"\\rightarrow"],
    "←": [r"\\leftarrow"],
    "↦": [r"\\mapsto"],
    "∈": [r"\\in"],
    "∉": [r"\\notin"],
    "∩": [r"\\cap"],
    "∪": [r"\\cup"],
    "⊂": [r"\\subset"],
    "⊆": [r"\\subseteq"],
    "⊃": [r"\\supset"],
    "⊇": [r"\\supseteq"],
    "∂": [r"\\partial"],
    "∇": [r"\\nabla"],
    "±": [r"\\pm"],
    "×": [r"\\times"],
    "·": [r"\\cdot"],
    "≠": [r"\\ne", r"\\neq"],
    "≈": [r"\\approx"],
    "∼": [r"\\sim"],
    "≡": [r"\\equiv"],
    "⊕": [r"\\oplus"],
    "⊗": [r"\\otimes"],
    "π": [r"\\pi"],
    "α": [r"\\alpha"],
    "β": [r"\\beta"],
    "γ": [r"\\gamma"],
    "δ": [r"\\delta"],
    "λ": [r"\\lambda"],
    "μ": [r"\\mu"],
    "σ": [r"\\sigma"],
    "φ": [r"\\phi", r"\\varphi"],
    "θ": [r"\\theta"],
}

def build_text_query(term: str, search_in: str = "text", include_math_map: bool = True) -> str:
    """
    Build a CirrusSearch srsearch string that prioritizes TEXT.
    - search_in: 'text' | 'title' | 'both'
    - include_math_map: add insource: variants for LaTeX macros when the term is a known glyph
    """
    clauses: List[str] = []
    q = _quote_for_search(term)
    if search_in in ("text", "both"):
        clauses.append(f"insource:{q}")  # literal in wikitext
        clauses.append(q)                # plain text index
    if search_in in ("title", "both"):
        clauses.append(f"intitle:{q}")
    if include_math_map:
        for k, variants in MATH_MAP.items():
            if k in term or term in (k,):
                for v in variants:
                    clauses.append(f"insource:{_quote_for_search(v)}")
    # If nothing added (shouldn't happen), fall back to quoted term
    s = " OR ".join(dict.fromkeys([c for c in clauses if c.strip()])) or q
    return s


def wiki_search_batch(term: str, limit: int = 20, offset: int = 0, *, search_in: str = "text", include_math_map: bool = True,
                      exclude: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """Return a batch of up to `limit` results using TEXT-first search."""
    import requests
    session = requests.Session()
    ua = "WikiSplice/1.6 (local script)"
    srsearch = build_text_query(term, search_in=search_in, include_math_map=include_math_map)
    for word in exclude or []:
        srsearch += " -" + _quote_for_search(word)  # leave out articles that mention it
    params = {
        "action": "query",
        "list": "search",
        "srnamespace": 0,  # main content
        "srsearch": srsearch,
        "srlimit": max(1, min(int(limit), 50)),
        "sroffset": max(0, int(offset)),
        "format": "json",
        "utf8": 1,
        "origin": "*",
    }
    r = session.get(WIKI_API, params=params, headers={"User-Agent": ua}, timeout=30)
    r.raise_for_status()
    data = r.json()
    out: List[Tuple[str, str]] = []
    for hit in data.get("query", {}).get("search", []):
        title = hit.get("title")
        if not title:
            continue
        url = WIKI_BASE + urllib.parse.quote(title.replace(" ", "_"))
        out.append((title, url))
    return out


# ------------------------------
# Sports blog search (web search restricted to sports sites)
# ------------------------------
DEFAULT_SPORTS_SITES = [
    "espn.com",
    "bleacherreport.com",
    "sbnation.com",
    "si.com",
    "cbssports.com",
    "sports.yahoo.com",
    "foxsports.com",
    "nbcsports.com",
    "theringer.com",
    "fansided.com",
    "barstoolsports.com",
    "thebiglead.com",
]

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def _host_matches(url: str, sites: List[str]) -> Optional[str]:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    for s in sites:
        s = s.lower().strip()
        if host == s or host.endswith("." + s):
            return s
    return None


def _ddg_search(query: str) -> List[Tuple[str, str]]:
    """DuckDuckGo HTML endpoint (no API key)."""
    import html as htmlmod
    import requests
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                      headers={"User-Agent": BROWSER_UA}, timeout=30)
    r.raise_for_status()
    out: List[Tuple[str, str]] = []
    for href, label in re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.S):
        href = htmlmod.unescape(href)
        if "duckduckgo.com/l/" in href:  # redirect wrapper
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = qs.get("uddg", [href])[0]
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com" in href:  # ads
            continue
        title = htmlmod.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        out.append((title or href, href))
    return out


def _bing_search(query: str) -> List[Tuple[str, str]]:
    """Bing web search RSS feed (fallback, no API key)."""
    import requests
    import xml.etree.ElementTree as ET
    r = requests.get("https://www.bing.com/search", params={"q": query, "format": "rss", "count": 30},
                     headers={"User-Agent": BROWSER_UA}, timeout=30)
    r.raise_for_status()
    out: List[Tuple[str, str]] = []
    for item in ET.fromstring(r.content).iter("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if link:
            out.append((title or link, link))
    return out


def _bing_news(query: str) -> List[Tuple[str, str]]:
    """Bing News RSS. News search indexes the article text, so it finds stories that
    mention the term in passing, not just ones with it in the headline."""
    import requests
    import xml.etree.ElementTree as ET
    r = requests.get("https://www.bing.com/news/search", params={"q": query, "format": "rss", "count": 50},
                     headers={"User-Agent": BROWSER_UA}, timeout=30)
    r.raise_for_status()
    out: List[Tuple[str, str]] = []
    for item in ET.fromstring(r.content).iter("item"):
        link = (item.findtext("link") or "").strip()
        if "apiclick.aspx" in link:  # tracking redirect; the real address is in ?url=
            link = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url", [link])[0]
        title = (item.findtext("title") or "").strip()
        if link:
            out.append((title or link, link))
    return out


def mentions_excluded(text: str, exclude: Optional[List[str]]) -> Optional[str]:
    low = text.lower()
    for word in exclude or []:
        if word and word.lower() in low:
            return word
    return None


def iter_sports_articles(term: str, sites: Optional[List[str]] = None, max_results: int = 200,
                         exclude: Optional[List[str]] = None):
    """
    Yield batches of sports articles about `term`, searching wider each round so
    the caller can stop as soon as it has enough screenshots:
      1. web search, a few sites at a time (mostly articles with the term in the title)
      2. news search, one site at a time (articles that mention it anywhere in the text)
      3. news search across all of those sites at once
    Results are interleaved across sites so one site doesn't dominate.
    """
    import time
    sites = [s.strip() for s in (sites or DEFAULT_SPORTS_SITES) if s.strip()]
    seen: set = set()
    total = 0

    def collect(results: List[Tuple[str, str]], allowed: List[str], by_site: dict) -> None:
        for title, url in results:
            site = _host_matches(url, allowed)
            key = url.split("#")[0].split("?")[0].rstrip("/")
            if not site or key in seen or url.lower().endswith(".pdf"):
                continue
            seen.add(key)
            word = mentions_excluded(title + " " + url, exclude)
            if word:
                print(f"[skip] Leaving out (mentions '{word}'): {title}")
                continue
            by_site[site].append((title, url))

    def interleave(by_site: dict) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        while any(by_site.values()):
            for s in sites:
                if by_site[s]:
                    out.append(by_site[s].pop(0))
        return out

    def web(query: str) -> List[Tuple[str, str]]:
        for engine in (_ddg_search, _bing_search):
            try:
                results = engine(query)
            except Exception as e:
                print(f"[warn] {engine.__name__.strip('_')} failed: {e}")
                results = []
            if results:
                return results
        return []

    def news(query: str) -> List[Tuple[str, str]]:
        try:
            return _bing_news(query)
        except Exception as e:
            print(f"[warn] news search failed: {e}")
            return []

    q = _quote_for_search(term)
    rounds = [
        ("Searching sports sites", [(web, q + " (" + " OR ".join(f"site:{s}" for s in sites[k:k + 3]) + ")", sites[k:k + 3])
                                    for k in range(0, len(sites), 3)]),
        ("Looking for articles that mention it in the story", [(news, f"{q} site:{s}", [s]) for s in sites]),
        ("Searching recent news", [(news, q, sites)]),
    ]
    for label, queries in rounds:
        print(f"[search] {label}...")
        by_site: dict = {s: [] for s in sites}
        for fn, query, allowed in queries:
            collect(fn(query), allowed, by_site)
            time.sleep(1.5)  # be polite to the search engines
        batch = interleave(by_site)[:max(0, max_results - total)]
        if batch:
            total += len(batch)
            print(f"[search] Found {len(batch)} more articles ({total} total)")
            yield batch
        if total >= max_results:
            return


def sports_search(term: str, sites: Optional[List[str]] = None, max_results: int = 40,
                  exclude: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """All rounds of iter_sports_articles as one list."""
    out: List[Tuple[str, str]] = []
    for batch in iter_sports_articles(term, sites, max_results=max_results, exclude=exclude):
        out += batch
    return out


def _is_wikipedia(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "").endswith("wikipedia.org")


# ------------------------------
# DOM helpers (injected JS)
# ------------------------------
WAIT_FONTS_JS = r"""
async () => { try { if (document.fonts && document.fonts.ready) { await document.fonts.ready; } } catch(e){} }
"""

FLUSH_LAYOUT_JS = r"""
() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
"""

MARK_MATCHES_JS = r"""
(opts => {
  const { term, caseSensitive, wholeWord, maxMatches, highlightAll } = opts;
  const exclude = (opts.exclude || []).map(w => w.toLowerCase()).filter(Boolean);
  const countOf = (hay, needle) => { let c = 0, i = 0; while ((i = hay.indexOf(needle, i)) !== -1) { c++; i += needle.length; } return c; };

  // Excluded words: skip pages that are mainly about them (they come up at least as
  // often as the search term in the article itself, ignoring menus and sidebars)
  if (exclude.length) {
    const main = document.querySelector('article, main, [role="main"], #mw-content-text') || document.body;
    const text = (main.innerText || '').toLowerCase();
    const termCount = countOf(text, term.toLowerCase());
    for (const w of exclude) {
      const c = countOf(text, w);
      if (c >= 3 && c >= termCount) return { ids: [], excluded: w };
    }
  }
  const BLOCK = 'p,li,td,th,h1,h2,h3,h4,h5,h6,blockquote,figcaption,dd,dt,caption';
  const blockMentionsExcluded = el => {
    if (!exclude.length) return false;
    const b = el.closest(BLOCK) || el;
    const t = (b.textContent || '').toLowerCase();
    return exclude.some(w => t.includes(w));
  };

  function isWordChar(ch) { return !!ch && /[\p{L}\p{N}_]/u.test(ch); }
  function normalizeSpaces(str) { return String(str).replace(/[\s\u00A0]/g, ' '); }

  // Only visible, real text (not <script> JSON, hidden menus, etc.)
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEXTAREA','TEMPLATE','TITLE','IFRAME','OPTION','SELECT']);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const p = n.parentElement;
      if (!p || SKIP.has(p.tagName.toUpperCase())) return NodeFilter.FILTER_REJECT;
      if (!p.getClientRects().length) return NodeFilter.FILTER_REJECT;
      if (p.checkVisibility && !p.checkVisibility({visibilityProperty: true})) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  // Collect first: replacing nodes mid-walk would end the walk after the first match.
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  const ids = [];

  for (const n of nodes) {
    if (!highlightAll && maxMatches && ids.length >= maxMatches) break;

    let t = normalizeSpaces(n.nodeValue || '');
    if (!t) continue;
    // Skip matches in a paragraph that mentions an excluded word
    if (exclude.length && (caseSensitive ? t : t.toLowerCase()).includes(caseSensitive ? term : term.toLowerCase())
        && blockMentionsExcluded(n.parentElement)) continue;

    const hay = caseSensitive ? t : t.toLowerCase();
    const needle = caseSensitive ? term : term.toLowerCase();
    let i = 0, last = 0;
    const frags = [];
    const spans = [];

    while ((i = hay.indexOf(needle, i)) !== -1) {
      const start = i, end = i + needle.length;
      if (wholeWord) {
        const prev = start > 0 ? t[start - 1] : '';
        const next = end < t.length ? t[end] : '';
        if (isWordChar(prev) || isWordChar(next)) { i = end; continue; }
      }
      frags.push(document.createTextNode(t.slice(last, start)));
      const span = document.createElement('span');
      span.textContent = t.slice(start, end);
      span.setAttribute('data-py-mark', '1');
      // stable metrics
      span.style.display = 'inline-block';
      span.style.lineHeight = '1';
      span.style.verticalAlign = 'baseline';
      spans.push(span);
      frags.push(span);
      last = end;
      i = end;
      if (!highlightAll && maxMatches && (ids.length + spans.length) >= maxMatches) break;
    }

    if (frags.length) {
      frags.push(document.createTextNode(t.slice(last)));
      const parent = n.parentNode;
      for (const f of frags) parent.insertBefore(f, n);
      parent.removeChild(n);
      for (const span of spans) {
        const id = `py_mark_${ids.length}_${Math.random().toString(36).slice(2,7)}`;
        span.id = id;
        ids.push(id);
        if (!highlightAll && maxMatches && ids.length >= maxMatches) break;
      }
    }
  }

  if (highlightAll) {
    if (!document.getElementById('py-mark-style')) {
      const style = document.createElement('style');
      style.id = 'py-mark-style';
      style.textContent = "span[data-py-mark]{background:rgba(255,230,80,.85);box-shadow:0 0 0 2px rgba(0,0,0,.15) inset;line-height:1;vertical-align:baseline;}";
      document.head.appendChild(style);
    }
  }
  return { ids, excluded: null };
})
"""

WIKI_CLEANUP_JS = r"""
(transparent) => {
  const hide = sel => { Array.from(document.querySelectorAll(sel)).forEach((el) => el.style.display = 'none'); };
  hide('#mw-panel'); hide('#vector-toc'); hide('#siteNotice'); hide('.vector-page-toolbar');
  if (!transparent) { document.documentElement.style.background = '#fff'; return; }
  const html = document.documentElement;
  const body = document.body;
  html.style.background = 'transparent';
  html.style.backgroundColor = 'transparent';
  body.style.background = 'transparent';
  body.style.backgroundColor = 'transparent';
}
"""

# Blogs/news sites: strip cookie banners, popups, sticky headers and ads so the
# text is unobstructed. (Hides them with CSS; never clicks "accept".)
BLOG_CLEANUP_JS = r"""
() => {
  if (!document.body) return;
  const style = document.createElement('style');
  style.textContent = `
    iframe, video, ins.adsbygoogle,
    [id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i],
    [id*="onetrust" i], [class*="onetrust" i], [id^="sp_message" i], [class*="sp_message" i],
    [class*="paywall" i], [id*="paywall" i], [aria-modal="true"], [role="dialog"],
    [id^="google_ads" i], [class*="ad-slot" i], [class*="AdSlot" i]
      { display: none !important; }
    html, body { overflow: visible !important; height: auto !important; }
  `;
  (document.head || document.documentElement).appendChild(style);
  document.documentElement.classList.remove('no-scroll');
  document.body.style.setProperty('position', 'static', 'important');
  for (const el of document.querySelectorAll('body *')) {
    const pos = getComputedStyle(el).position;
    if (pos === 'fixed' || pos === 'sticky') el.style.setProperty('display', 'none', 'important');
  }
}
"""

GET_VIEWPORT_RECT_JS = r"""
(id) => {
  const el = document.getElementById(id);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}
"""

# Is the word actually drawn on screen? Catches text that's "visible" to the DOM but
# hidden in practice: clipped carousels, collapsed sections, covered by an overlay.
HIT_TEST_JS = r"""
(id) => {
  const el = document.getElementById(id);
  if (!el) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return false;
  // A see-through parent (e.g. a page that fades in once its scripts load) hides it too
  if (el.checkVisibility && !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) return false;
  const pts = [[0.5, 0.5], [0.25, 0.5], [0.75, 0.5]];
  return pts.some(([fx, fy]) => {
    const hit = document.elementFromPoint(r.left + r.width * fx, r.top + r.height * fy);
    return !!hit && (hit === el || el.contains(hit));
  });
}
"""

# Add blank space above/below the page content (added to any padding from earlier matches)
ADD_PAGE_PADDING_JS = r"""
([top, bottom]) => {
  const s = document.body.style;
  s.paddingTop = (parseFloat(s.paddingTop) || 0) + top + 'px';
  s.paddingBottom = (parseFloat(s.paddingBottom) || 0) + bottom + 'px';
}
"""

SCROLL_TO_CENTER_JS = r"""
(id) => { const el = document.getElementById(id); if (el) el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'}); }
"""

# ------------------------------
# Screenshot capture
# ------------------------------
def capture_wiki_screenshots(
    pages: List[Tuple[str, str]],
    term: str,
    outdir: str,
    frame_size=(1920, 1080),
    *,
    max_matches_per_page: int = 3,
    case_sensitive: bool = True,
    whole_word: bool = True,
    dpr: float = 3.0,
    target_word_px: int = 600,
    framing_zoom: float = 1.0,
    center_eps_px: float = 0.05,
    center_max_iter: int = 6,
    pad_to_center: bool = False,
    highlight_all: bool = False,
    settle_ms: int = 60,
    max_total_matches: Optional[int] = None,
    start_index: int = 1,
    exclude: Optional[List[str]] = None,
    skip: Optional[dict] = None,
    indices: Optional[List[int]] = None,
    capped: Optional[list] = None,
    seen_hashes: Optional[set] = None,
    transparent: bool = False,
) -> List[dict]:
    """
    exclude: leave out pages/paragraphs about these words.
    skip:    {url: n} — matches already captured on that page (for a second visit).
    indices: page numbers to use in file names (default: start_index, start_index+1, ...).
    capped:  if given, pages that had more matches than max_matches_per_page are
             appended as (title, url, index, matches_taken) so the caller can come back.
    """
    skip = skip or {}
    seen_hashes = seen_hashes if seen_hashes is not None else set()

    def is_duplicate(fpath: str) -> bool:
        """Identical to a shot we already have (e.g. a name repeated in the same layout)? Then drop it."""
        import hashlib
        try:
            with open(fpath, "rb") as fh:
                digest = hashlib.md5(fh.read()).hexdigest()
        except OSError:
            return False
        if digest in seen_hashes:
            os.remove(fpath)
            print("[skip] Same as an earlier screenshot")
            return True
        seen_hashes.add(digest)
        return False
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. `pip install playwright` and run `playwright install chromium`.")

    vw, vh = frame_size
    aspect = vw / vh
    os.makedirs(outdir, exist_ok=True)
    saved: List[dict] = []

    def q(v: float) -> float:
        return max(1.0 / dpr, round(v * dpr) / dpr)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=dpr, user_agent=BROWSER_UA)
        # Skip video/audio downloads; they're never in the screenshot and slow pages down.
        context.route("**/*", lambda route: route.abort() if route.request.resource_type == "media" else route.continue_())
        page = context.new_page()
        page.set_default_timeout(20000)

        def centered_shot(mid: str, fpath: str) -> Optional[dict]:
            """
            Scroll the word to the middle of the window and crop around it, so every
            shot is exactly the frame's shape with the word dead center. (Page
            coordinates are unreliable on blogs that scroll inside an inner container.)
            Words too close to the top or bottom of a page get blank space added
            there so they can still be centered.
            """
            r = page.evaluate(GET_VIEWPORT_RECT_JS, mid)
            if not r or r["w"] <= 0 or r["h"] <= 0:
                return None
            cw = max(32.0, vw * (float(r["w"]) / max(1.0, float(target_word_px)))) * max(0.25, float(framing_zoom))
            cw = q(cw); ch = q(cw / aspect)
            # Grow the window if the crop is bigger than it (large framing zoom)
            need = {"width": max(vw, int(cw) + 2), "height": max(vh, int(ch) + 2)}
            if page.viewport_size != need:
                page.set_viewport_size(need)
            for _ in range(2):  # twice: lazy images above can shift the text after the first scroll
                page.evaluate(SCROLL_TO_CENTER_JS, mid)
                page.wait_for_timeout(max(settle_ms, 250))
            r = page.evaluate(GET_VIEWPORT_RECT_JS, mid)
            if not r or r["w"] <= 0 or r["h"] <= 0:
                return None
            for _ in range(8):  # pages often fade in after loading; give it up to ~2 s
                if page.evaluate(HIT_TEST_JS, mid):
                    break
                page.wait_for_timeout(250)
            else:
                print("[skip] Match is hidden on the page (carousel, collapsed section or overlay)")
                return None
            r = page.evaluate(GET_VIEWPORT_RECT_JS, mid)  # may have moved while fading in
            cy = float(r["y"]) + float(r["h"]) / 2.0
            short_top = ch / 2.0 - cy                          # word too close to the top of the page
            short_bottom = cy + ch / 2.0 - need["height"]      # ...or to the bottom
            if short_top > 0.5 or short_bottom > 0.5:
                page.evaluate(ADD_PAGE_PADDING_JS, [max(0.0, short_top) + 2, max(0.0, short_bottom) + 2])
                page.wait_for_timeout(max(settle_ms, 100))
                page.evaluate(SCROLL_TO_CENTER_JS, mid)
                page.wait_for_timeout(max(settle_ms, 100))
                r = page.evaluate(GET_VIEWPORT_RECT_JS, mid)
                if not r or r["w"] <= 0 or r["h"] <= 0:
                    return None
            cx = float(r["x"]) + float(r["w"]) / 2.0
            cy = float(r["y"]) + float(r["h"]) / 2.0
            x = q(max(0.0, min(cx - cw / 2.0, need["width"] - cw)))
            y = q(max(0.0, min(cy - ch / 2.0, need["height"] - ch)))
            page.screenshot(path=fpath, clip={"x": x, "y": y, "width": cw, "height": ch}, omit_background=bool(transparent))
            return {"path": fpath, "dx_css": cx - (x + cw / 2.0), "dy_css": cy - (y + ch / 2.0), "cw_css": cw, "ch_css": ch}

        for n_page, (title, url) in enumerate(pages):
            i = indices[n_page] if indices else start_index + n_page
            if max_total_matches is not None and len(saved) >= max_total_matches:
                break
            word = mentions_excluded(title + " " + url, exclude)
            if word:
                print(f"[skip] Leaving out (mentions '{word}'): {title}")
                continue
            print(f"[page] {title} — {url}")
            wiki = _is_wikipedia(url)
            if page.viewport_size != {"width": vw, "height": vh}:
                page.set_viewport_size({"width": vw, "height": vh})
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("body", state="attached", timeout=10000)
                if not wiki:
                    # Blogs render article text with JS; give them a moment.
                    try:
                        page.wait_for_load_state("load", timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(800)
                if wiki:
                    page.evaluate(WIKI_CLEANUP_JS, bool(transparent))
                else:
                    page.evaluate(BLOG_CLEANUP_JS)
            except Exception as e:
                print(f"[skip] Failed to load {title}: {e}")
                continue

            page.evaluate(WAIT_FONTS_JS)

            remaining = None if max_total_matches is None else max(0, max_total_matches - len(saved))
            if remaining is not None and remaining == 0:
                break
            page_max = int(max_matches_per_page if remaining is None else min(max_matches_per_page, remaining))
            already = int(skip.get(url, 0))

            try:
                found = page.evaluate(MARK_MATCHES_JS, {
                    "term": term,
                    "caseSensitive": bool(case_sensitive),
                    "wholeWord": bool(whole_word),
                    "maxMatches": already + page_max + 1,  # +1 tells us whether there are more
                    "highlightAll": bool(highlight_all),
                    "exclude": list(exclude or []),
                })
            except Exception as e:
                print(f"[skip] Could not scan {title}: {e}")
                continue
            if found.get("excluded"):
                print(f"[skip] Leaving out (mostly about '{found['excluded']}'): {title}")
                continue
            all_ids = found.get("ids") or []
            mark_ids = all_ids[already:already + page_max]
            if capped is not None and len(all_ids) > already + page_max:
                capped.append((title, url, i, already + len(mark_ids)))
            if not mark_ids:
                if not already:
                    print(f"[skip] No matches for '{term}' in {title}")
                continue

            page.evaluate(WAIT_FONTS_JS)
            page.evaluate(FLUSH_LAYOUT_JS)

            for j, mid in enumerate(mark_ids, already + 1):
                if max_total_matches is not None and len(saved) >= max_total_matches:
                    break

                fname = f"{i:03d}_{j:02d}_" + _safe_slug(title) + ".png"
                try:
                    shot = centered_shot(mid, _abs(os.path.join(outdir, fname)))
                except Exception as e:
                    print(f"[skip] Screenshot failed on {title}: {e}")
                    continue
                if shot and not is_duplicate(shot["path"]):
                    saved.append(shot)
                    print(f"[ok] {title} [{j}/{already + len(mark_ids)}] -> {fname} (residual: {shot['dx_css']:.3f}, {shot['dy_css']:.3f})")


        context.close()
        browser.close()

    return saved


# ------------------------------
# After Effects JSX
# ------------------------------
def write_jsx(
    images: List[dict],
    out_jsx: str,
    *,
    fps: float = 60.0,
    shot_dur: float = 0.12,
    width: int = 1920,
    height: int = 1080,
    scale_pct: float = 100.0,
    punch: float = 0.0,
    dpr: float = 3.0,
    name: str = "WikiCollage",
) -> None:
    items = [{
        "path": _abs(d["path"]).replace("\\", "\\\\"),
        "dx": float(d.get("dx_css", 0.0)),
        "dy": float(d.get("dy_css", 0.0)),
    } for d in images]
    total_dur = max(shot_dur * max(1, len(items)), shot_dur)

    jsx = f"""
(function() {{
  function getOrCreateProject() {{ if (!app.project) app.newProject(); return app.project; }}
  function scaleToFillAndCenter(layer, compW, compH, baseScale, dx_css, dy_css, dpr) {{
    var srcW = layer.source.width, srcH = layer.source.height;
    var sX = (compW / srcW) * 100; var sY = (compH / srcH) * 100;
    var s = Math.max(sX, sY);
    s = s * (baseScale/100.0);
    layer.property('Scale').setValue([s, s]);

    var shiftX = (-dx_css * dpr) * (s/100.0);
    var shiftY = (-dy_css * dpr) * (s/100.0);
    layer.property('Position').setValue([compW/2 + shiftX, compH/2 + shiftY]);
  }}
  app.beginUndoGroup('Wiki Collage Centered');
  try {{
  var proj = getOrCreateProject();
  var comp = proj.items.addComp({json.dumps(name)}, {width}, {height}, 1.0, {total_dur}, {fps});
  var folder = proj.items.addFolder({json.dumps(name + " crops")});
  var items = {json.dumps(items)}
  var missing = 0;
  for (var i=0;i<items.length;i++) {{
    var rec = items[i];
    var f = new File(rec.path);
    if (!f.exists) {{ missing++; continue; }}
    var it = proj.importFile(new ImportOptions(f));
    it.parentFolder = folder;
    var L = comp.layers.add(it);
    L.startTime = i*{shot_dur};
    // Each shot is on screen only until the next one starts (the last one holds to the end)
    L.outPoint  = (i == items.length - 1) ? comp.duration : Math.min(comp.duration, L.startTime + {shot_dur});
    scaleToFillAndCenter(L, {width}, {height}, {scale_pct}, rec.dx, rec.dy, {dpr});
    {"var S=L.property('Scale'); var sNow=S.value[0]; S.setValueAtTime(L.startTime,[sNow,sNow]); S.setValueAtTime(L.outPoint,[sNow*"+str(1.0+punch)+", sNow*"+str(1.0+punch)+"]); S.setInterpolationTypeAtKey(1, KeyframeInterpolationType.BEZIER); S.setInterpolationTypeAtKey(2, KeyframeInterpolationType.BEZIER);" if punch and punch>0 else ""}
  }}
  comp.openInViewer();
  if (missing) alert('WikiSplice: ' + missing + ' of ' + items.length + ' screenshots were missing (moved or deleted?) and were skipped.');
  }} catch (e) {{
    alert('WikiSplice could not build the composition:\\n' + e.toString() + (e.line ? ' (line ' + e.line + ')' : ''));
  }}
  app.endUndoGroup();
}})();
"""
    with open(out_jsx, "w", encoding="utf-8") as f:
        f.write(jsx)


def maybe_run_after_effects(out_jsx: str, ae_version: str = "Adobe After Effects 2026") -> Tuple[bool, str]:
    """
    Run the JSX in After Effects. Launches AE first if needed and waits until it
    can accept scripts. Returns (ok, human-readable message).
    """
    jsx_abs = _abs(out_jsx)
    if os.name == "nt":
        os.startfile(jsx_abs)  # type: ignore
        return True, f"Opened {jsx_abs}"
    if sys.platform != "darwin":
        msg = f"Open this JSX in After Effects: {jsx_abs}"
        print(msg)
        return False, msg

    import subprocess
    import tempfile
    import time

    def osa(script: str, timeout: float = 600) -> Tuple[int, str]:
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stderr or r.stdout).strip()
        except subprocess.TimeoutExpired:
            return 1, "timed out"

    def asq(text: str) -> str:  # AppleScript string literal
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    app_q = asq(ae_version)
    code, out = osa(f'application {app_q} is running', timeout=20)
    if code != 0:
        msg = f"Couldn't find \"{ae_version}\". Pick your After Effects version and try again. ({out})"
        print("[error]", msg)
        return False, msg

    if out != "true":
        print(f"[ae] Launching {ae_version} (this can take a minute)...")
        subprocess.run(["open", "-a", ae_version], check=False)
        # AE accepts AppleScript before it's ready for scripts; wait for a probe to actually run.
        marker = os.path.join(tempfile.gettempdir(), f"wikisplice_ae_ready_{os.getpid()}")
        if os.path.exists(marker):
            os.remove(marker)
        probe = (f"try {{ var f = new File({json.dumps(marker)}); f.open('w'); f.write('1'); f.close(); }} catch (e) {{}}")
        deadline = time.time() + 240
        while time.time() < deadline and not os.path.exists(marker):
            time.sleep(3)
            osa(f'tell application {app_q} to DoScript {asq(probe)}', timeout=30)
        if os.path.exists(marker):
            os.remove(marker)
        else:
            time.sleep(10)  # scripts may not be allowed to write files; give it extra time and send anyway

    code, out = osa(f'tell application {app_q}\n  activate\n  DoScriptFile (POSIX file {asq(jsx_abs)})\nend tell')
    if code != 0:
        if "-1743" in out or "Not authorized" in out:
            msg = ("macOS blocked WikiSplice from controlling After Effects. Open System Settings → Privacy & Security → "
                   "Automation, and allow Terminal (or whichever app launched WikiSplice) to control After Effects. Then try again.")
        else:
            msg = f"After Effects reported an error: {out}"
        print("[error]", msg)
        return False, msg
    msg = f"Sent to {ae_version}. Your composition should be open there now."
    print("[ok]", msg, jsx_abs)
    return True, msg


# ------------------------------
# CLI
# ------------------------------
OUTPUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def default_run_dir(term: str) -> str:
    """output/<term>/<date_time>/ — every run gets its own folder, so nothing is ever overwritten."""
    import time
    base = os.path.join(OUTPUT_ROOT, _safe_slug(term), time.strftime("%Y-%m-%d_%H-%M-%S"))
    path, n = base, 2
    while os.path.exists(path):  # two runs in the same second
        path = f"{base}_{n}"
        n += 1
    return path


def main():
    ap = argparse.ArgumentParser(description="Wikipedia / sports blogs → After Effects collage with precise centering. Prefer a point-and-click UI? Run: python app.py")
    ap.add_argument("--term", required=True)
    ap.add_argument("--limit", type=int, default=20, help="Wikipedia search batch size per API call")
    ap.add_argument("--out", default=None,
                    help="Output directory (screens + JSX). Default: output/<term>/<date_time>/, a new folder every run")
    ap.add_argument("--speed", type=float, default=0.12, help="Seconds per still")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)

    ap.add_argument("--ignore-case", action="store_true", help="Match without case sensitivity (default: case-sensitive)")
    ap.add_argument("--no-whole-word", action="store_true", help="Allow substrings (default: whole word only)")
    ap.add_argument("--highlight-all", action="store_true", help="Highlight ALL matches in page")

    ap.add_argument("--max-matches-per-page", type=int, default=3, help="Screenshots per page (upper bound)")
    ap.add_argument("--max-total-matches", type=int, default=50, help="Stop after this many screenshots overall")

    ap.add_argument("--dpr", type=float, default=3.0, help="Device scale factor for crisp PNGs")
    ap.add_argument("--target-word-px", type=int, default=600, help="Desired final word width in comp pixels")
    ap.add_argument("--framing-zoom", type=float, default=1.0, help=">1 captures more area around the word")

    ap.add_argument("--center-eps-px", type=float, default=0.05, help="Max center error (CSS px) after quantization")
    ap.add_argument("--center-max-iter", type=int, default=6, help="Re-center iterations")
    ap.add_argument("--pad-to-center", action="store_true", help="(No longer needed: words near the top or bottom of a page are always padded so they're centered)")

    ap.add_argument("--settle-ms", type=int, default=60)

    ap.add_argument("--ae-punch", type=float, default=0.0, help="End scale multiplier-1 (e.g., 0.08 = +8%%)")
    ap.add_argument("--scale", type=float, default=100.0, help="Base Scale %% for each layer (used with scale-to-fill)")
    ap.add_argument("--run-ae", action="store_true")
    ap.add_argument("--ae-version", default="Adobe After Effects 2026")

    ap.add_argument("--search-in", choices=["text", "title", "both"], default="text", help="Where to search in MediaWiki index")
    ap.add_argument("--no-math-map", action="store_true", help="Disable glyph→LaTeX expansion for text search")

    ap.add_argument("--source", choices=["wikipedia", "sports", "both"], default="wikipedia",
                    help="Where to find pages: Wikipedia, sports blogs/news sites, or both mixed together")
    ap.add_argument("--sports-sites", default=",".join(DEFAULT_SPORTS_SITES),
                    help="Comma-separated sports sites to search when --source is sports/both")
    ap.add_argument("--max-articles", type=int, default=200,
                    help="Safety limit on sports articles to visit when --source is sports/both "
                         "(it stops sooner once it has enough screenshots)")
    ap.add_argument("--transparent", action="store_true",
                    help="Wikipedia: transparent page background instead of white (for compositing over other footage)")
    ap.add_argument("--exclude", default="",
                    help="Comma-separated words to leave out, e.g. 'basketball,recruiting'. Skips articles "
                         "about them and matches in paragraphs that mention them")

    args = ap.parse_args()

    outdir = os.path.abspath(os.path.expanduser(args.out or default_run_dir(args.term)))
    screens_dir = os.path.join(outdir, "screens")
    os.makedirs(screens_dir, exist_ok=True)
    print(f"[info] Saving to {outdir}")

    exclude = [w.strip() for w in args.exclude.split(",") if w.strip()]
    if exclude:
        print(f"[info] Leaving out anything about: {', '.join(exclude)}")

    def wiki_batches():
        offset = 0
        while True:
            pages = wiki_search_batch(args.term, offset=offset, limit=args.limit, search_in=args.search_in,
                                      include_math_map=(not args.no_math_map), exclude=exclude)
            if not pages:
                return
            yield pages
            offset += len(pages)
            if len(pages) < args.limit:
                return

    def page_batches():
        """Batches of pages to visit, searching wider each time; stops being asked once we have enough."""
        sources = []
        if args.source in ("wikipedia", "both"):
            sources.append(wiki_batches())
        if args.source in ("sports", "both"):
            sources.append(iter_sports_articles(args.term, args.sports_sites.split(","),
                                                max_results=args.max_articles, exclude=exclude))
        while sources:  # alternate between sources when mixing ("both")
            for src in list(sources):
                batch = next(src, None)
                if batch is None:
                    sources.remove(src)
                else:
                    yield batch

    target = args.max_total_matches
    common = dict(
        frame_size=(args.width, args.height),
        case_sensitive=(not args.ignore_case),
        whole_word=(not args.no_whole_word),
        dpr=args.dpr,
        target_word_px=args.target_word_px,
        framing_zoom=args.framing_zoom,
        center_eps_px=args.center_eps_px,
        center_max_iter=args.center_max_iter,
        pad_to_center=args.pad_to_center,
        highlight_all=args.highlight_all,
        settle_ms=args.settle_ms,
        exclude=exclude,
        transparent=args.transparent,
    )

    images: List[dict] = []
    visited: set = set()
    capped: list = []  # pages with more matches than --max-matches-per-page
    seen_hashes: set = set()  # drop identical frames
    page_index = 1
    batches = page_batches()
    while True:
        remaining = None if target is None else max(0, target - len(images))
        if remaining == 0:
            break  # check before searching further, so we don't run an extra search round
        pages = next(batches, None)
        if pages is None:
            break
        pages = [(t, u) for t, u in pages if u not in visited]
        visited.update(u for _, u in pages)
        if not pages:
            continue
        imgs = capture_wiki_screenshots(
            pages, args.term, screens_dir,
            max_matches_per_page=args.max_matches_per_page if remaining is None else min(args.max_matches_per_page, remaining),
            max_total_matches=remaining, start_index=page_index, capped=capped, seen_hashes=seen_hashes, **common,
        )
        images.extend(imgs)
        page_index += len(pages)
        print(f"[progress] {len(images)}" + (f" of {target}" if target else "") + " screenshots")

    # Ran out of articles? Go back to pages that had more matches than we took.
    while target and len(images) < target and capped:
        print(f"[search] No more new articles; taking extra shots from {len(capped)} pages that had more matches...")
        revisit, capped = capped, []
        before = len(images)
        imgs = capture_wiki_screenshots(
            [(t, u) for t, u, _, _ in revisit], args.term, screens_dir,
            # Spread what's still needed across these pages so each is visited once
            max_matches_per_page=max(args.max_matches_per_page, -(-(target - len(images)) // len(revisit))),
            max_total_matches=target - len(images),
            indices=[i for _, _, i, _ in revisit], skip={u: n for _, u, _, n in revisit}, capped=capped,
            seen_hashes=seen_hashes, **common,
        )
        images.extend(imgs)
        print(f"[progress] {len(images)} of {target} screenshots")
        if len(images) == before:
            break

    if target and 0 < len(images) < target:
        print(f"[warn] Only found {len(images)} of {target} screenshots: there were no more matching articles."
              + (" Leaving out fewer words may find more." if exclude else ""))

    if not images:
        hint = " Try turning off case-sensitive/whole-word matching, or a different source." if args.source != "wikipedia" else " Try --ignore-case, --search-in both, or --source sports."
        sys.exit(f"[error] No screenshots captured for '{args.term}'.{hint}")

    out_jsx = os.path.join(outdir, f"build_wikisplice_{_safe_slug(args.term)}.jsx")
    write_jsx(images, out_jsx, fps=args.fps, shot_dur=args.speed, width=args.width, height=args.height, scale_pct=args.scale, dpr=args.dpr, punch=args.ae_punch,
              name=f"WikiSplice - {args.term}")
    print(f"[ok] JSX written: {out_jsx}")

    if args.run_ae:
        maybe_run_after_effects(out_jsx, ae_version=args.ae_version)
    else:
        print("Open JSX in After Effects:", out_jsx)


if __name__ == "__main__":
    main()