# Project rules for TDEE Tools

## Before building

- Mobile-first. Design for 390px viewport first.
- No horizontal overflow at any width.
- All calculator logic must be client-side JavaScript (no backend).
- Use Mifflin-St Jeor equation for BMR (most validated, cited on all pages).
- Keep each page under 50KB of HTML/CSS/JS combined.
- Every tool must show formula and sources. No black-box results.
- Design stance: Refined Utility (white background, blue accents, warmer than finance sites).

## Before committing

- Check responsive layout at 390px, 768px, and 1280px viewports.
- Verify calculations match manual checks: use known TDEE values from literature.
- Verify no console errors in browser.

## Domain

- Placeholder: easytdee.com (swap once Jonathan registers on Cloudflare)
- AdSense slot IDs: placeholder values, swap once site is approved

## Data sources

- Mifflin-St Jeor BMR formula: St Jeor ST, et al. JADA 1990
- Activity multipliers: Katch-McArdle convention
- Macro ranges: Dietary Guidelines for Americans 2020-2025
