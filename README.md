# wikisplice

A powerful tool for creating dynamic video collages from Wikipedia search results. wikisplice searches Wikipedia for a given term, captures screenshots of matching text on relevant pages, and automatically generates an After Effects composition with precisely centered, animated sequences.

## What It Does

wikisplice performs the following workflow:

1. **Search Wikipedia** - Uses the MediaWiki API to find pages containing your search term
2. **Capture Screenshots** - Opens each page with Playwright, highlights matching text, and captures cropped screenshots centered on the matches
3. **Generate After Effects Script** - Creates a JSX file that builds an animated composition in Adobe After Effects
4. **Optional Auto-Launch** - Can automatically open and run the generated script in After Effects

The result is a smooth, timed sequence showing your search term across multiple Wikipedia contexts, perfect for educational content, visual research, or artistic projects.

## Installation

```bash
# Install Python dependencies
pip install playwright requests

# Install browser for Playwright
playwright install chromium
```

## Basic Usage

```bash
python wikisplice.py --term "your search term" --run-ae
```

This will create a `wiki_collage` directory with screenshots and an After Effects JSX script, and will run the JSX in After Effects Automatically.

## Command Line Arguments

### Required Arguments

- `--term` - The search term to find on Wikipedia pages

### Output Settings

- `--out` (default: `./wiki_collage`) - Output directory for screenshots and JSX file
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

## Examples

### Basic Example
```bash
python wikisplice.py --term "Python programming"
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

The tool creates the following structure in your output directory:

```
wiki_collage/
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

- Python 3.7+
- Chromium browser (installed via Playwright)
- Adobe After Effects (for JSX execution)
- macOS, Windows, or Linux

## Troubleshooting

- **"playwright not installed"**: Run `pip install playwright && playwright install chromium`
- **No matches found**: Try `--ignore-case` or `--search-in both`
- **Screenshots too small**: Increase `--target-word-px` or `--framing-zoom`
- **After Effects won't launch**: Check `--ae-version` matches your installation
