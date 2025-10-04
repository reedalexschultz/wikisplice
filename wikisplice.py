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


def wiki_search_batch(term: str, limit: int = 20, offset: int = 0, *, search_in: str = "text", include_math_map: bool = True) -> List[Tuple[str, str]]:
    """Return a batch of up to `limit` results using TEXT-first search."""
    import requests
    session = requests.Session()
    ua = "WikiSplice/1.6 (local script)"
    srsearch = build_text_query(term, search_in=search_in, include_math_map=include_math_map)
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

  function isWordChar(ch) { return !!ch && /[\p{L}\p{N}_]/u.test(ch); }
  function normalizeSpaces(str) { return String(str).replace(/[\s\u00A0]/g, ' '); }

  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const ids = [];

  while (walker.nextNode()) {
    if (!highlightAll && maxMatches && ids.length >= maxMatches) break;

    const n = walker.currentNode;
    let t = normalizeSpaces(n.nodeValue || '');
    if (!t) continue;

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
  return ids;
})
"""

GET_RECT_JS = r"""
(id) => {
  const el = document.getElementById(id);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height };
}
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
) -> List[dict]:
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. `pip install playwright` and run `playwright install chromium`.")

    vw, vh = frame_size
    aspect = vw / vh
    os.makedirs(outdir, exist_ok=True)
    saved: List[dict] = []

    def q(v: float) -> float:
        return max(1.0 / dpr, round(v * dpr) / dpr)

    def clamp_crop(x: float, y: float, cw: float, ch: float, page_w: float, page_h: float):
        if x < 0:
            cw += x
            x = 0.0
        if y < 0:
            ch += y
            y = 0.0
        if x + cw > page_w:
            cw = page_w - x
        if y + ch > page_h:
            ch = page_h - y
        min_css = 1.0 / max(1.0, float(dpr))
        cw = max(min_css, cw)
        ch = max(min_css, ch)
        return q(x), q(y), q(cw), q(ch)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=dpr)
        page = context.new_page()
        page.set_default_timeout(20000)

        def page_dims():
            return page.evaluate("() => ({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")

        for i, (title, url) in enumerate(pages, 1):
            if max_total_matches is not None and len(saved) >= max_total_matches:
                break
            try:
                page.goto(url, wait_until="domcontentloaded")
            except Exception as e:
                print(f"[skip] Failed to load {title}: {e}")
                continue

            # Hide chrome + transparent background
            page.evaluate("""() => {
                const hide = id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; };
                hide('mw-panel'); hide('vector-toc'); hide('siteNotice');
                const html = document.documentElement;
                const body = document.body;
                html.style.background = 'transparent';
                html.style.backgroundColor = 'transparent';
                body.style.background = 'transparent';
                body.style.backgroundColor = 'transparent';
            }""")

            page.evaluate(WAIT_FONTS_JS)

            remaining = None if max_total_matches is None else max(0, max_total_matches - len(saved))
            if remaining is not None and remaining == 0:
                break
            page_max = int(max_matches_per_page if remaining is None else min(max_matches_per_page, remaining))

            mark_ids = page.evaluate(MARK_MATCHES_JS, {
                "term": term,
                "caseSensitive": bool(case_sensitive),
                "wholeWord": bool(whole_word),
                "maxMatches": page_max,
                "highlightAll": bool(highlight_all),
            })
            if not mark_ids:
                print(f"[skip] No matches for '{term}' in {title}")
                continue

            page.evaluate(WAIT_FONTS_JS)
            page.evaluate(FLUSH_LAYOUT_JS)

            dims = page_dims()
            page_w, page_h = float(dims["w"]), float(dims["h"])

            for j, mid in enumerate(mark_ids, 1):
                if max_total_matches is not None and len(saved) >= max_total_matches:
                    break

                r = page.evaluate(GET_RECT_JS, mid)
                if not r or r["w"] <= 0 or r["h"] <= 0:
                    continue

                w_word = float(r["w"])
                cx = float(r["x"]) + w_word / 2.0
                cy = float(r["y"]) + float(r["h"]) / 2.0

                cw = max(32.0, (vw * (w_word / max(1.0, float(target_word_px)))))
                ch = cw / aspect

                z = max(0.25, float(framing_zoom))
                cw *= z
                ch = cw / aspect

                cw = q(cw); ch = q(ch)

                desired_x = cx - cw / 2.0
                desired_y = cy - ch / 2.0

                if pad_to_center:
                    dims = page_dims()
                    page_w, page_h = float(dims["w"]), float(dims["h"])
                    pad_top    = max(0.0, -desired_y)
                    pad_bottom = max(0.0, desired_y + ch - page_h)
                    if pad_top or pad_bottom:
                        page.evaluate("""(pads) => {
                            const [t, b] = pads;
                            const s = document.body.style;
                            s.paddingTop   = `${t}px`;
                            s.paddingBottom= `${b}px`;
                        }""", [pad_top, pad_bottom])
                        page.wait_for_timeout(settle_ms)
                        page.evaluate(WAIT_FONTS_JS)
                        page.evaluate(FLUSH_LAYOUT_JS)
                        r = page.evaluate(GET_RECT_JS, mid)
                        if not r or r["w"] <= 0 or r["h"] <= 0:
                            continue
                        w_word = float(r["w"])
                        cx = float(r["x"]) + w_word / 2.0
                        cy = float(r["y"]) + float(r["h"]) / 2.0
                        desired_x = cx - cw / 2.0
                        desired_y = cy - ch / 2.0

                dims = page_dims()
                page_w, page_h = float(dims["w"]), float(dims["h"])
                x = max(0.0, min(desired_x, page_w - cw))
                y = max(0.0, min(desired_y, page_h - ch))

                for _ in range(int(center_max_iter)):
                    vx = cx - (x + cw / 2.0)
                    vy = cy - (y + ch / 2.0)
                    if abs(vx) <= center_eps_px and abs(vy) <= center_eps_px:
                        break
                    x = max(0.0, min(x + vx, page_w - cw))
                    y = max(0.0, min(y + vy, page_h - ch))

                res_dx = cx - (x + cw/2.0)
                res_dy = cy - (y + ch/2.0)

                x, y, cw, ch = clamp_crop(x, y, cw, ch, page_w, page_h)

                fname = f"{i:03d}_{j:02d}_" + _safe_slug(title) + ".png"
                fpath = _abs(os.path.join(outdir, fname))
                clip = {"x": float(x), "y": float(y), "width": float(cw), "height": float(ch)}
                try:
                    page.screenshot(path=fpath, clip=clip, omit_background=True)
                except Exception as e:
                    msg = str(e)
                    if "Clipped area is either empty or outside the resulting image" in msg or "outside the resulting image" in msg:
                        elem_id = f"py_capture_{i}_{j}_{int(x)}_{int(y)}"
                        page.evaluate("""(cfg) => {
                            const {id,x,y,w,h} = cfg;
                            let el = document.getElementById(id);
                            if (!el) {
                              el = document.createElement('div');
                              el.id = id;
                              document.body.appendChild(el);
                            }
                            Object.assign(el.style, {
                              position: 'absolute',
                              left: x + 'px',
                              top: y + 'px',
                              width: w + 'px',
                              height: h + 'px',
                              background: 'transparent',
                              outline: 'none',
                              pointerEvents: 'none',
                              zIndex: '2147483647',
                              transform: 'translateZ(0)'
                            });
                        }""", {"id": elem_id, "x": clip["x"], "y": clip["y"], "w": clip["width"], "h": clip["height"]})
                        handle = page.query_selector(f"#{elem_id}")
                        if handle is None:
                            raise RuntimeError("Failed to create capture element")
                        handle.screenshot(path=fpath, omit_background=True)
                        page.evaluate("(id) => { const el = document.getElementById(id); if (el) el.remove(); }", elem_id)
                        print(f"[ok/element] {title} [{j}/{len(mark_ids)}] -> {fname}")
                    else:
                        raise

                saved.append({
                    "path": fpath,
                    "dx_css": float(res_dx),
                    "dy_css": float(res_dy),
                    "cw_css": float(cw),
                    "ch_css": float(ch),
                })
                print(f"[ok] {title} [{j}/{len(mark_ids)}] -> {fname} (residual: {res_dx:.3f}, {res_dy:.3f})")

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
  var proj = getOrCreateProject();
  var comp = proj.items.addComp('WikiCollage', {width}, {height}, 1.0, {total_dur}, {fps});
  var folder = proj.items.addFolder('WikiCrops');
  var items = {json.dumps(items)}
  for (var i=0;i<items.length;i++) {{
    var rec = items[i];
    var f = new File(rec.path);
    if (!f.exists) continue;
    var it = proj.importFile(new ImportOptions(f));
    it.parentFolder = folder;
    var L = comp.layers.add(it);
    L.startTime = i*{shot_dur};
    L.outPoint  = comp.duration;
    scaleToFillAndCenter(L, {width}, {height}, {scale_pct}, rec.dx, rec.dy, {dpr});
    {"var S=L.property('Scale'); var sNow=S.value[0]; S.setValueAtTime(L.startTime,[sNow,sNow]); S.setValueAtTime(L.outPoint,[sNow*"+str(1.0+punch)+", sNow*"+str(1.0+punch)+"]); S.setInterpolationTypeAtKey(1, KeyframeInterpolationType.BEZIER); S.setInterpolationTypeAtKey(2, KeyframeInterpolationType.BEZIER);" if punch and punch>0 else ""}
  }}
  comp.openInViewer();
  app.endUndoGroup();
}})();
"""
    with open(out_jsx, "w", encoding="utf-8") as f:
        f.write(jsx)


def maybe_run_after_effects(out_jsx: str, ae_version: str = "Adobe After Effects 2025") -> None:
    jsx_abs = _abs(out_jsx)
    if sys.platform == "darwin":
        import shutil, subprocess
        osa = shutil.which("osascript")
        if osa:
            script = f"""tell application "{ae_version}"
  activate
  DoScriptFile (POSIX file "{jsx_abs}")
end tell"""
            subprocess.run([osa, "-e", script], check=False)
            print(f"Sent JSX to {ae_version}: {jsx_abs}")
        else:
            print("osascript not found; open JSX manually:", jsx_abs)
    elif os.name == "nt":
        os.startfile(jsx_abs)  # type: ignore
    else:
        print("Open this JSX in After Effects:", jsx_abs)


# ------------------------------
# CLI
# ------------------------------
def main():
    ap = argparse.ArgumentParser(description="Wikipedia → AE collage with precise centering (text search)")
    ap.add_argument("--term", required=True)
    ap.add_argument("--limit", type=int, default=20, help="Wikipedia search batch size per API call")
    ap.add_argument("--out", default="./wiki_collage", help="Output directory (screens + JSX)")
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
    ap.add_argument("--pad-to-center", action="store_true", help="Pad page top/bottom so the word is perfectly centered vertically")

    ap.add_argument("--settle-ms", type=int, default=60)

    ap.add_argument("--ae-punch", type=float, default=0.0, help="End scale multiplier-1 (e.g., 0.08 = +8%)")
    ap.add_argument("--scale", type=float, default=100.0, help="Base Scale % for each layer (used with scale-to-fill)")
    ap.add_argument("--run-ae", action="store_true")
    ap.add_argument("--ae-version", default="Adobe After Effects 2025")

    ap.add_argument("--search-in", choices=["text", "title", "both"], default="text", help="Where to search in MediaWiki index")
    ap.add_argument("--no-math-map", action="store_true", help="Disable glyph→LaTeX expansion for text search")

    args = ap.parse_args()

    outdir = os.path.abspath(os.path.expanduser(args.out))
    screens_dir = os.path.join(outdir, "screens")
    os.makedirs(screens_dir, exist_ok=True)

    images: List[dict] = []
    offset = 0
    while True:
        remaining = None if args.max_total_matches is None else max(0, args.max_total_matches - len(images))
        if remaining is not None and remaining == 0:
            break

        pages = wiki_search_batch(args.term, limit=args.limit, offset=offset, search_in=args.search_in, include_math_map=(not args.no_math_map))
        if not pages:
            break

        imgs = capture_wiki_screenshots(
            pages,
            args.term,
            screens_dir,
            frame_size=(args.width, args.height),
            max_matches_per_page=args.max_matches_per_page if remaining is None else min(args.max_matches_per_page, remaining),
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
            max_total_matches=remaining,
        )
        images.extend(imgs)
        offset += len(pages)
        if len(pages) < args.limit:
            break

    if not images:
        sys.exit("No images available")

    out_jsx = os.path.join(outdir, f"build_wikisplice_{_safe_slug(args.term)}.jsx")
    write_jsx(images, out_jsx, fps=args.fps, shot_dur=args.speed, width=args.width, height=args.height, scale_pct=args.scale, dpr=args.dpr, punch=args.ae_punch)
    print(f"[ok] JSX written: {out_jsx}")

    if args.run_ae:
        maybe_run_after_effects(out_jsx, ae_version=args.ae_version)
    else:
        print("Open JSX in After Effects:", out_jsx)


if __name__ == "__main__":
    main()