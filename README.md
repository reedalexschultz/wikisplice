# wikisplice

Make fast-cut video montages of a word or name appearing across the web.

Type something like **"Shohei Ohtani"** or **"Renaissance"**. wikisplice finds pages that mention it (on **Wikipedia** or on **sports blogs** such as ESPN, Bleacher Report, and SB Nation), takes a screenshot centered on each mention, and builds an **Adobe After Effects** composition that flashes through them in sequence.

---

## The easy way (no terminal needed)

1. **Download** this folder to your computer.
2. **Double-click `Start WikiSplice.command`** (Mac) or **`Start WikiSplice.bat`** (Windows).
   - The first time, it sets itself up automatically. This takes a few minutes and needs an internet connection.
   - On a Mac, if it says the file "can't be opened", right-click it, choose **Open**, then click **Open** again.
3. A page opens in your web browser. Type what you're looking for, pick where to search, and press **Start**.
4. Screenshots appear as they're captured. When it's done, click **Open in After Effects** to build the video.

Leave the small black terminal window open while you use it. Close it when you're finished.

> **Need Python?** If the launcher says Python isn't installed, get it from [python.org/downloads](https://www.python.org/downloads/) (on Windows, tick "Add Python to PATH" during install), then double-click the launcher again.

### Where should it look?

| Option | Best for |
|---|---|
| **Wikipedia** | Topics, places, historical figures, science and math terms |
| **Sports blogs** | Athletes, coaches, and teams, especially players who don't appear in many Wikipedia articles |
| **Both** | Mixing encyclopedic and sports coverage in one montage |

You can edit the list of sports sites right in the app, for example to add `mlb.com`, `nba.com`, or your team's blog.

### Where do my files go?

Everything is saved in the `output/` folder. Each search gets a folder named after what you searched, and **every run gets its own dated folder inside it**, so earlier screenshots are never cleared or overwritten:

```
output/
└── Shohei_Ohtani/
    ├── 2026-10-15_10-42-03/
    │   ├── screens/                              ← all the screenshots (PNG)
    │   └── build_wikisplice_Shohei_Ohtani.jsx    ← the After Effects script
    └── 2026-10-16_09-05-51/                      ← a later run
```

Old runs stay until you delete them yourself. After Effects links to these PNGs rather than copying them, so keep a run's folder as long as you use its After Effects project. The `output/` folder is listed in `.gitignore`, so screenshots are never committed to git.

Click **Show files** in the app to open the folder. To build the video by hand, open After Effects and choose **File → Scripts → Run Script File…**, then pick the `.jsx` file.

---

## Command line (for power users)

Everything the app does is also available from the terminal.

```bash
pip install -r requirements.txt
playwright install chromium

# Open the point-and-click app
python app.py

# Or run directly
python wikisplice.py --term "your search term"

# Search sports blogs for a player
python wikisplice.py --term "Paul Skenes" --source sports --max-total-matches 30
```

## Command Line Arguments

### Required Arguments

- `--term` - The search term to find

### Where to Search

- `--source` (choices: `wikipedia`, `sports`, `both`, default: `wikipedia`) - Search Wikipedia, sports blogs/news sites, or mix both
- `--sports-sites` (default: ESPN, Bleacher Report, SB Nation, SI, CBS Sports, Yahoo Sports, Fox Sports, NBC Sports, The Ringer, FanSided, Barstool, The Big Lead) - Comma-separated list of sites to search with `--source sports`/`both`
- `--max-articles` (default: `40`) - Maximum number of sports articles to visit

### Output Settings

- `--out` (default: `output/<term>/<date_time>/`) - Output directory for screenshots and JSX file. By default every run gets a new folder, so nothing is overwritten
- `--run-ae` - Automatically launch After Effects and run the generated script
- `--ae-version` (default: `"Adobe After Effects 2025"`) - Name of After Effects application for auto-launch

### Search Configuration

- `--limit` (default: `20`) - Number of Wikipedia pages to fetch per API call
- `--search-in` (choices: `text`, `title`, `both`, default: `text`) - Where to search in MediaWiki index
- `--no-math-map` - Disable automatic expansion of mathematical symbols to LaTeX equivalents
- `--max-total-matches` (default: `50`) - Maximum total screenshots to capture across all pages
- `--max-matches-per-page` (default: `3`) - Maximum screenshots per individual Wikipedia page

### Text Matching Options

- `--ignore-case` - Make search case-insensitive (default: case-sensitive)
- `--no-whole-word` - Allow substring matches (default: whole word only)
- `--highlight-all` - Highlight all matches on each page (default: only capture specific matches)

### Visual Composition Settings

- `--width` (default: `1920`) - Composition width in pixels
- `--height` (default: `1080`) - Composition height in pixels
- `--fps` (default: `60.0`) - Frames per second for the composition
- `--speed` (default: `0.12`) - Duration in seconds for each screenshot
- `--scale` (default: `100.0`) - Base scale percentage for each layer
- `--ae-punch` (default: `0.0`) - End scale multiplier for zoom effect (e.g., 0.08 = +8% zoom)

### Screenshot Capture Settings

- `--dpr` (default: `3.0`) - Device pixel ratio for high-resolution screenshots
- `--target-word-px` (default: `600`) - Desired width of the matched word in final composition pixels
- `--framing-zoom` (default: `1.0`) - Multiplier for capture area around the word (>1 captures more context)

### Centering and Precision

- `--center-eps-px` (default: `0.05`) - Maximum acceptable centering error in CSS pixels
- `--center-max-iter` (default: `6`) - Maximum iterations for centering refinement
- `--pad-to-center` - Add padding to pages to achieve perfect vertical centering
- `--settle-ms` (default: `60`) - Milliseconds to wait for page layout to stabilize

## Command-Line Examples

### Basic Example
```bash
python wikisplice.py --term "Python programming"
```

### Sports Player Montage
```bash
python wikisplice.py --term "Caitlin Clark" \
  --source sports \
  --max-total-matches 40 --max-matches-per-page 3 \
  --framing-zoom 2.0 --speed 0.08 --run-ae
```

Searches ESPN, Bleacher Report, SB Nation and other sports sites for articles mentioning the player, then screenshots each mention.

### Only Specific Sites
```bash
python wikisplice.py --term "Victor Wembanyama" \
  --source sports \
  --sports-sites "nba.com,espn.com,poundingtherock.com"
```

### High-Quality Educational Content
```bash
python wikisplice.py --term "Calculus" \
  --framing-zoom 4.00 \
  --target-word-px 810 \
  --center-eps-px 0.05 --center-max-iter 18 \
  --pad-to-center \
  --max-total-matches 20 --max-matches-per-page 10 \
  --width 1920 --height 1920 --dpr 5.0 --fps 60 --speed 0.05 --run-ae
```

This example creates a high-resolution square composition (1920x1920) with:
- Ultra-high quality screenshots (5x device pixel ratio)
- Large framing area (4x zoom out for context)
- Big, readable text (810px target width)
- Precise centering with padding
- Fast transitions (0.05 seconds per shot)
- Automatic After Effects launch

### Quick Research Collage
```bash
python wikisplice.py --term "quantum mechanics" \
  --max-total-matches 30 \
  --speed 0.08 \
  --framing-zoom 2.0 \
  --highlight-all \
  --run-ae
```

### Mathematical Term Search
```bash
python wikisplice.py --term "∫" \
  --search-in both \
  --target-word-px 400 \
  --framing-zoom 3.0 \
  --max-matches-per-page 5
```

This searches for the integral symbol, automatically expanding to LaTeX variants like `\int`, and searches both page text and titles.

### Case-Insensitive Historical Search
```bash
python wikisplice.py --term "renaissance" \
  --ignore-case \
  --search-in both \
  --max-total-matches 40 \
  --speed 0.15 \
  --ae-punch 0.1
```

## Output Structure

Each run creates this structure in its output directory (by default `output/<term>/<date_time>/`):

```
output/<term>/<date_time>/
├── screens/
│   ├── 001_01_Page_Title_Name.png
│   ├── 001_02_Page_Title_Name.png
│   └── ...
└── build_wikisplice_search_term.jsx
```

- `screens/` contains all captured screenshots
- The JSX file can be opened in After Effects to build the composition

## Mathematical Symbol Support

wikisplice automatically recognizes mathematical symbols and expands searches to include LaTeX equivalents:

- `∫` → searches for `\int`
- `∑` → searches for `\sum`
- `√` → searches for `\sqrt`
- `≈` → searches for `\approx`
- And many more...

## Tips and Best Practices

1. **High-Quality Output**: Use `--dpr 3.0` or higher for crisp screenshots
2. **Better Framing**: Increase `--framing-zoom` to show more context around matches
3. **Precise Centering**: Use `--pad-to-center` for mathematical or technical terms where centering is crucial
4. **Fast Iterations**: Start with low `--max-total-matches` for quick tests
5. **Square Compositions**: Use equal width/height for social media content
6. **Mathematical Terms**: Let the math map feature work automatically, or use `--search-in both` for comprehensive coverage

## System Requirements

- Python 3.9+
- Chromium browser (installed via Playwright)
- Adobe After Effects (for JSX execution)
- macOS, Windows, or Linux

## Troubleshooting

- **"playwright not installed"**: Run `pip install playwright && playwright install chromium`
- **No matches found**: Try `--ignore-case` or `--search-in both`. For athletes and other people with thin Wikipedia coverage, try `--source sports`
- **A sports site gives no results**: Some sites block automated browsers or sit behind paywalls; wikisplice skips those and keeps going. Add other sites with `--sports-sites`
- **Screenshots too small**: Increase `--target-word-px` or `--framing-zoom`
- **After Effects won't launch**: Check `--ae-version` matches your installation
