"""Production CI gate for the Easy TDEE static site.

Behaviour-focused checks over the built static files: page structure, SEO
assets, JSON-LD validity, sitemap/robots wiring, JavaScript syntax, and the
formula/source invariants that make these calculators trustworthy. Pure
stdlib unittest so it runs anywhere with Python 3.11 (+ node for JS checks).
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://easytdee.com"
NODE = shutil.which("node")

# Minimal deterministic DOM so a page's inline handlers run under node with no
# browser and no dependencies: inputs read from __inputs, outputs land in __out
# keyed by element id, alert() is captured instead of thrown.
DOM_STUB = r"""
const __inputs = %s, __sex = %s, __out = {};
function __el(id) {
  return {
    get value() { return __inputs[id]; },
    set value(v) { __inputs[id] = v; },
    set textContent(v) { __out[id] = String(v); },
    set innerHTML(v) { __out[id] = String(v); },
    set placeholder(v) {},
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    scrollIntoView() {},
  };
}
const document = { getElementById: __el, querySelector() { return { value: __sex }; } };
function alert(msg) { __out.__alert = String(msg); }
"""


def run_inline(name, inputs, sex, call):
    """Run a page's inline JS under node against DOM_STUB; return the id->text
    map the handler wrote (with __alert set if a validation guard fired)."""
    inline_js = "\n".join(b for k, b in scripts(read(ROOT / name)) if k == "inline")
    src = (DOM_STUB % (json.dumps(inputs), json.dumps(sex)) + inline_js
           + f"\n{call};\nprocess.stdout.write(JSON.stringify(__out));\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        r = subprocess.run([NODE, path], capture_output=True, text=True)
    finally:
        Path(path).unlink()
    if r.returncode != 0:
        raise RuntimeError(f"{name} inline JS failed under node:\n{r.stderr}")
    return json.loads(r.stdout)


def digits(text):
    """Numeric value of a displayed string, ignoring locale grouping/units."""
    return int(re.sub(r"\D", "", text))

# ponytail: regex HTML/script scan, fine for these hand-written static files.
# Swap to html.parser only if pages start being template-generated.
SCRIPT_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)


def html_pages():
    return sorted(ROOT.glob("*.html"))


def read(path):
    return path.read_text(encoding="utf-8")


def scripts(html):
    """Yield (kind, body) for every <script>; kind in {ldjson, external, inline}."""
    for m in SCRIPT_RE.finditer(html):
        attrs, body = m.group("attrs").lower(), m.group("body")
        if "application/ld+json" in attrs:
            yield "ldjson", body
        elif "src=" in attrs:
            yield "external", body
        else:
            yield "inline", body


def loc_to_path(loc):
    """Map a sitemap <loc> URL to its local file path."""
    rel = loc.strip()[len(SITE):].lstrip("/")
    return ROOT / (rel or "index.html")


class PageDiscovery(unittest.TestCase):
    def test_discovery_non_vacuous(self):
        pages = html_pages()
        self.assertGreaterEqual(len(pages), 5, "expected the full site, discovery came up short")
        self.assertIn("index.html", {p.name for p in pages})


class PageStructure(unittest.TestCase):
    def test_single_nonempty_title(self):
        for p in html_pages():
            titles = re.findall(r"<title>(.*?)</title>", read(p), re.S | re.I)
            self.assertEqual(len(titles), 1, f"{p.name}: expected exactly one <title>")
            self.assertTrue(titles[0].strip(), f"{p.name}: <title> is empty")

    def test_single_h1(self):
        for p in html_pages():
            self.assertEqual(len(re.findall(r"<h1[\s>]", read(p), re.I)), 1,
                             f"{p.name}: expected exactly one <h1>")

    def test_meta_description_present(self):
        for p in html_pages():
            m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', read(p), re.I)
            self.assertIsNotNone(m, f"{p.name}: missing meta description")
            self.assertTrue(m.group(1).strip(), f"{p.name}: empty meta description")

    def test_canonical_present(self):
        for p in html_pages():
            m = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', read(p), re.I)
            self.assertIsNotNone(m, f"{p.name}: missing canonical link")
            self.assertTrue(m.group(1).startswith(SITE), f"{p.name}: canonical not on site origin")


class StructuredData(unittest.TestCase):
    def test_jsonld_parseable(self):
        found = 0
        for p in html_pages():
            for kind, body in scripts(read(p)):
                if kind != "ldjson":
                    continue
                found += 1
                try:
                    data = json.loads(body)
                except json.JSONDecodeError as e:
                    self.fail(f"{p.name}: invalid JSON-LD: {e}")
                self.assertIn("@context", data, f"{p.name}: JSON-LD missing @context")
        self.assertGreater(found, 0, "no JSON-LD found on any page - structured data regressed")


class SitemapAndRobots(unittest.TestCase):
    def setUp(self):
        self.sitemap = ROOT / "sitemap.xml"
        self.robots = ROOT / "robots.txt"

    def test_assets_exist(self):
        self.assertTrue(self.sitemap.is_file(), "sitemap.xml missing")
        self.assertTrue(self.robots.is_file(), "robots.txt missing")

    def test_robots_points_to_sitemap(self):
        self.assertRegex(read(self.robots), r"(?im)^\s*Sitemap:\s*\S*sitemap\.xml\s*$")

    def _locs(self):
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        root = ET.parse(self.sitemap).getroot()
        return [loc.text for loc in root.iter(f"{ns}loc")]

    def test_sitemap_valid_and_nonempty(self):
        locs = self._locs()
        self.assertGreater(len(locs), 0, "sitemap has no <url> entries")

    def test_sitemap_urls_map_to_files(self):
        for loc in self._locs():
            self.assertTrue(loc_to_path(loc).is_file(),
                            f"sitemap URL {loc} has no local file")

    def test_public_pages_are_listed(self):
        listed = {loc_to_path(loc).name for loc in self._locs()}
        for p in html_pages():
            self.assertIn(p.name, listed, f"{p.name} is not in sitemap.xml")


class JavaScriptSyntax(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_inline_and_file_js_syntax(self):
        checked = 0
        with tempfile.TemporaryDirectory() as tmp:
            snippets = []
            for p in html_pages():
                for i, (kind, body) in enumerate(scripts(read(p))):
                    if kind == "inline" and body.strip():
                        snippets.append((f"{p.stem}_{i}.js", body))
            for js in ROOT.glob("js/*.js"):
                snippets.append((js.name, read(js)))

            for name, body in snippets:
                f = Path(tmp) / name
                f.write_text(body, encoding="utf-8")
                r = subprocess.run(["node", "--check", str(f)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{name} failed node --check:\n{r.stderr}")
                checked += 1
        self.assertGreater(checked, 0, "no JavaScript found to syntax-check")


class FormulaInvariants(unittest.TestCase):
    """These encode the calculator behaviour AGENTS.md commits to: Mifflin-St
    Jeor BMR, standard activity multipliers, macro calorie densities, the
    3500 kcal/lb rule, and BMI thresholds. A change here should be deliberate."""

    def inline(self, name):
        return "\n".join(b for k, b in scripts(read(ROOT / name)) if k == "inline")

    @unittest.skipUnless(NODE, "node not installed")
    def test_tdee_execution_matches_mifflin_st_jeor(self):
        cases = (
            # age 30, 70 kg, 175 cm, activity 1.55
            ("male", 1649, 2556),
            ("female", 1483, 2298),
        )
        for sex, expected_bmr, expected_tdee in cases:
            with self.subTest(sex=sex):
                out = run_inline(
                    "tdee-calculator.html",
                    {"units": "metric", "age": "30", "weight": "70",
                     "heightCm": "175", "activity": "1.55"},
                    sex, "calculateTDEE()")
                self.assertNotIn("__alert", out,
                                 f"validation blocked calc: {out.get('__alert')}")
                self.assertEqual(
                    digits(out["bmrResult"]), expected_bmr,
                    f"displayed {sex} BMR drifted - check Mifflin-St Jeor sex adjustment")
                self.assertEqual(
                    digits(out["tdeeResult"]), expected_tdee,
                    "displayed TDEE drifted - check BMR × activity")

    def test_tdee_activity_multipliers_consistent(self):
        html = read(ROOT / "tdee-calculator.html")
        expected = {"1.2", "1.375", "1.55", "1.725", "1.9"}
        options = set(re.findall(r'<option value="(1\.\d+)"', html))
        formula = set(re.findall(r"BMR × (1\.\d+)", html))
        self.assertEqual(options, expected, "activity <option> values drifted")
        self.assertEqual(formula, expected, "activity values in the formula box drifted")

    def test_macro_calorie_densities_and_splits(self):
        js = self.inline("macro-calculator.html")
        self.assertIn("/ 4", js, "protein/carb should be 4 kcal/g")
        self.assertIn("/ 9", js, "fat should be 9 kcal/g")
        splits = re.findall(
            r"proteinPct = (0\.\d+); fatPct = (0\.\d+); carbPct = (0\.\d+)", js)
        self.assertEqual(len(splits), 3, "expected cut/maintain/bulk macro splits")
        for p, f, c in splits:
            total = round(float(p) + float(f) + float(c), 4)
            self.assertEqual(total, 1.0, f"macro split {p}/{f}/{c} must sum to 100%")

    @unittest.skipUnless(NODE, "node not installed")
    def test_calorie_deficit_clamp_and_3500_model(self):
        # rate 2 lb/wk -> dailyDeficit = round(2*3500/7) = 1000 (the 3500 model);
        # raw target = 1500 - 1000 = 500, which Math.max must clamp up to 1200.
        out = run_inline(
            "calorie-deficit-calculator.html",
            {"tdee": "1500", "currentWeight": "200", "goalWeight": "150", "rate": "2"},
            None, "calculateDeficit()")
        self.assertNotIn("__alert", out, f"validation blocked calc: {out.get('__alert')}")
        self.assertEqual(digits(out["dailyDeficit"]), 1000,
                         "daily deficit drifted - check the 3500 kcal/lb model")
        self.assertEqual(digits(out["targetCalories"]), 1200,
                         "1200 kcal floor not enforced - check Math.max clamp")

    def test_bmi_formula_and_thresholds(self):
        js = self.inline("bmi-calculator.html")
        self.assertIn("weightKg / (heightM * heightM)", js, "BMI = kg / m^2 changed")
        for threshold in ("18.5", "25", "30", "24.9"):
            self.assertIn(threshold, js, f"BMI threshold {threshold} missing")

    def test_every_calculator_shows_formula_and_source(self):
        for name in ("tdee-calculator.html", "macro-calculator.html",
                     "calorie-deficit-calculator.html", "bmi-calculator.html"):
            html = read(ROOT / name)
            self.assertIn("formula-box", html, f"{name}: no formula shown")
            self.assertIn("source-note", html, f"{name}: no source cited")

    def test_tdee_cites_mifflin_st_jeor_source(self):
        html = read(ROOT / "tdee-calculator.html")
        self.assertIn("Mifflin-St Jeor", html)
        self.assertIn("St Jeor", html)
        self.assertIn("1990", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
