# Risk Trainer design

The reference for the web app's interface: the Blueprint theme as it is today (UI-01). It describes `src/risk_trainer/web/static/app.css` and the templates, it doesn't change them. UI work follows this file ([AGENTS.md](../AGENTS.md)); when a change alters what's described here, the same pull request updates this file and `docs/design/`.

Snapshot taken 17 Nov 2026. When this file and the code differ, the code is what ships; fix the file in a pull request.

Risk Trainer belongs to the Bearing Quest project family on a light path and keeps its own theme. See [Relationship to Bearing Quest](#relationship-to-bearing-quest). Bearing Quest is a project-family name, never a company.

## What's in `docs/design/`

| Path | What it is | How to use it |
|---|---|---|
| `tokens.json` | Every custom property from `app.css`: colors for light and dark, the two font stacks and the page width, each with a usage note | The written palette. `tests/unit/test_ui_design_snapshot.py` (UI-04) fails if it and `app.css` differ in either theme |
| `bearing-quest-lockup.svg` | Byte copy of the static lockup (SHA-256 `723322e0…b9d5`, pinned in `test_r12_static_assets.py`) | The family strip. Use it through `<img>`; its mask ids (`bq-lm`, `bq-lh`) would collide if two were inlined |
| `app-reference.css` | Copy of `app.css` as of this snapshot | A reference for layout and component values, not production CSS. It isn't compared byte for byte; refresh it with token changes |
| `screens/*.png` | Four screens, light and dark, 1280 px wide, full page: `home`, `exercise`, `debrief`, `preview` | The visual target for UI changes |

The Risk Trainer mark (the padlock) and the home page art are inline SVG in `base.html` and `home.html`, not files. They are decorative and carry `aria-hidden="true"`.

## Colors

Light is the default. Every pair that carries text or a control boundary is checked in both themes by `tests/unit/test_nfr_a11y_theme.py`: text at 4.5:1, control outlines and focus rings at 3:1.

| Token | Light | Dark | Role |
|---|---|---|---|
| `bg` | `#F4F8FB` | `#0A1520` | Page |
| `surface` | `#FFFFFF` | `#0F1E2D` | Cards, nav bar, slot bar, inputs, tables |
| `surface2` | `#EAF1F7` | `#13263A` | Panels inside a surface, preview banner, learner text |
| `text` | `#0E1B2A` | `#E3EEF6` | Body and headings |
| `muted` | `#46586B` | `#9DB2C5` | Labels, hints, footer |
| `border` | `#C3D2DF` | `#24405A` | Dividers and card outlines. Decoration only |
| `control` | `#5E7488` | `#6F8DA8` | Outline of every input, select, choice row, switch button and unfilled pip |
| `accent` | `#006A7A` | `#4FD6E8` | Links, primary buttons, selected choice, finding IDs, card corner marks, filled pips |
| `on-accent` | `#FFFFFF` | `#04131C` | Text on an accent fill |
| `accent-soft` | `#DDF1F4` | `#0E3340` | Selected choice row background |
| `focus` | `#9A3412` | `#FFBF47` | Focus ring |
| `error` | `#B42318` | `#FF8A80` | Error summary |
| `draft` | `#8A4B00` | `#FFD08A` | Draft pill and banner text, approver-feedback and why-not rules |
| `draft-bg` | `#FFF4E5` | `#33240A` | Draft pill and banner background |

Fixed in both themes (rules in `app.css`, not custom properties): the masthead ground `#071019` with a 32 px grid of `rgba(79, 214, 232, 0.07)` lines and a `#1C3A4F` bottom border, masthead text `#E3EEF6` and `#9DB2C5`, its focus color `#FFBF47`, and the family strip (`#03080D` ground, `#9DB2C5` text, `#1C3A4F` border; 9.20:1).

Color is never the only signal: the selected choice has a thicker border as well as a fill, filled pips sit beside a text status, the draft state has the words "DRAFT — not published.", and errors have a heading.

## Themes

- Dark applies under `prefers-color-scheme: dark` unless `<html data-theme="light">`, and always with `data-theme="dark"`. The dark values are written twice in `app.css` (the auto block and the chosen block); a test requires them equal, and so does UI-04.
- The Auto, Light and Dark switch sits in the nav bar. It stores the choice in `localStorage` as `rt-theme` (per browser, every access in try/catch) and is hidden without JavaScript, where the page follows the device.
- `static/theme.js` runs in `<head>` without `defer`, so `data-theme` is set before first paint. The CSP allows no inline script, so this can't be inline.

## Type

- **Inter** for UI and body, weights 400 and 600, v4.1 subset to Latin-1 plus common punctuation (`unicode-range` in `app.css`). **IBM Plex Mono** for IDs, labels, the tagline, the switch and difficulty, weights 400 and 500.
- Self-hosted woff2 under `/static/<version>/fonts/`, each with its OFL file beside it. No font CDN. The four SHA-256 values are pinned in `test_r12_static_assets.py`; provenance is in `docs/decisions.md` (2026-10-15 and 2026-10-29).
- Body is `1rem/1.55`. Headings are 600 with `h1` at `line-height: 1.25`. Finding headings are `1.25rem`, the score `1.4rem`, labels (`dt`) mono `.85rem`, tags and the footer `.8rem` to `.9rem`. The home masthead title is `clamp(1.6rem, 5vw, 2.2rem)`; the slim masthead title is `1.15rem`.

## Spacing and layout

There are no spacing tokens. Spacing is hard-coded rem in `app.css`, and this section records what is used today rather than a scale.

- Content width is `--page: 52rem`, centered, with `1rem` side padding. Main has `.5rem` top and `2rem` bottom padding.
- Common gaps: `.25rem` to `.5rem` inside components, `.75rem` to `1.1rem` for card padding, `1.25rem` between cards and findings, `1.5rem` to `2rem` for page sections.
- Radius: `3px` for ID chips, `4px` for cards and panels, `6px` for buttons, inputs and choice rows, `999px` for tags.
- Touch targets: buttons and switch buttons at least `44px`, choice rows at least `48px`.
- No horizontal scroll at 390 px; an e2e test checks every page.

## Banner and masthead

Every page starts with the same header stack, top to bottom:

1. **Preview and draft banners**, only when they apply (R18). `banner-preview` ("Local preview. Not the live site.") on `surface2`; `banner-draft` ("DRAFT — not published.") on `draft-bg` with a 2px `draft` border. Both are `role="note"` and use the page's tokens, so they change with the theme.
2. **Family strip**: the lockup (30 px high) and "project family". No links, nothing focusable, so the skip link stays the first tab stop.
3. **Masthead**: a dark blueprint ground in both themes. Home uses the full masthead: the circuit-and-padlock art (520 px wide, `aria-hidden`), the "Risk Trainer" name and the mono tagline, all centered. Every other page uses the slim masthead: a 30 px padlock mark beside the name, linking home.
4. **Nav bar** on `surface`: Main navigation on the left, the theme switch on the right.

## Components

| Component | Class | Notes |
|---|---|---|
| Button | `.button`, `.exercise button[type="submit"]` | `accent` fill, `on-accent` text, 600 weight, 6px radius, 44px minimum; underline on hover. One primary action per screen |
| Scenario card | `.scenario-card` | `surface`, 1px `border`, with `accent` corner marks top-left and bottom-right. Grid of `minmax(18rem, 1fr)` |
| Tag and pill | `.tag`, `.tag-draft` | Mono `.8rem`, outlined in `control`; the draft variant uses `draft` and `draft-bg` |
| Difficulty | `.difficulty` | Mono label with `accent` pips |
| Context panel | `.context`, `.capacity` | `surface` panel; the capacity note is `surface2` with a 4px `accent` left rule |
| Slot bar | `.slot-bar`, `.slot-pips`, `.pip` | Sticky at the top, with a text status. App.js measures its height for `scroll-padding-top` so focus is never hidden (WCAG 2.4.11) |
| Finding | `.finding`, `.finding-id`, `.signals` | `surface` card; the ID chip is `accent` with `on-accent` mono text; signals on `surface2` |
| Choice row | `.choices`, `.choice` | Outlined in `control`; selected is a 2px `accent` border on `accent-soft` with 1px less padding so the row doesn't shift; disabled is dashed with struck-through muted text |
| Form fields | `select`, `textarea`, `label`, `.hint` | `control` outline, 6px radius, 44px select |
| Error summary | `.error-summary` | 2px `error` border on `surface`, `error` heading |
| Score and table | `.score`, `table` | Rules in `border`; the table scrolls inside `.table-wrap` |
| Debrief | `.finding-debrief`, `.learner-text`, `.approver-feedback`, `.why-not`, `.peers` | Section rule in `border`, echoed text on `surface2`, 4px `draft` left rule for feedback, peer list in two columns |
| Footer | `.site-footer` | `muted`, with the ISC2 line |
| Skip link and hidden text | `.skip-link`, `.visually-hidden` | The skip link is the first focusable element |

## Focus, contrast and motion

- Every focusable element gets a 3px solid `focus` ring with a 2px offset. A choice row shows the ring on the row, not on the radio. The masthead sets its own `#FFBF47` ring because its ground is dark in both themes.
- The light focus color is `#9A3412`, because the earlier `#FFBF47` was 1.64:1 on white. The 2026-10-15 row records this.
- Control outlines use `control`, not `border`, so they meet 3:1.
- The app has no animation beyond the browser's.

## CSP and markup rules

- Strict CSP (`web/middleware.py`): `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'`. Fonts fall under `default-src`.
- No inline `<script>`, no `<style>`, no `style=` attributes and no `on*=` handlers. Styling goes in `app.css` as classes; behavior goes in `theme.js` and `app.js`.
- No CDN and no third-party origin. htmx is vendored.
- Inline `<svg>` is allowed. A decorative one has `aria-hidden="true"` and `focusable="false"`; a test checks the home and about pages.
- Static files are served under a path-versioned URL (`/static/<sha256-12>/…`), so every asset reference goes through `static_url()`.
- Adding a stylesheet, script or font changes the asset counts and font list pinned in `test_r12_static_assets.py`; that is intended, and it needs the owner's decision.

## Relationship to Bearing Quest

Risk Trainer joined the Bearing Quest family on 29 Oct 2026 on a light path ([decisions](decisions.md), 2026-10-29). It shares only:

- the Inter and IBM Plex Mono fonts, self-hosted and pinned,
- the family strip with the unedited Bearing Quest lockup.

It does **not** use the Bearing Quest design system's color tokens, ground colors or accent, and it has no spacing tokens. The Blueprint theme (teal accent on a deep-blue ground, the circuit-and-padlock masthead) stays Risk Trainer's own. This is a recorded departure, with the reason, in `docs/decisions.md`. Other family apps, for example QuestVector, use the shared tokens plus their own accent; Risk Trainer's strip exists because it keeps its own colors.

## Screens

`screens/` holds one full-page capture per theme of each screen:

| File | Screen | Notes |
|---|---|---|
| `home-*.png` | Home, the full masthead and one scenario card | |
| `exercise-*.png` | A scenario with all five findings set to Transfer | The sticky slot bar appears mid-page in a full-page capture; in use it sits at the top of the viewport |
| `debrief-*.png` | The results page after submitting | |
| `preview-*.png` | Home under `rt preview`: the preview banner and a draft pill | |

They are captured by **Dusten, outside the sandbox**, because Chromium can't start inside Claude Code's sandbox: macOS denies its Mach bootstrap check-in (`bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer…: Permission denied (1100)`), so `BrowserType.launch` fails with `Target page, context or browser has been closed`. Agents don't retry outside the sandbox; they ask Dusten to run this from the repo root in a normal terminal:

```
PYTHONPATH=. uv run python capture_screens.py docs/design/screens
```

with this as `capture_screens.py`. It uses the same server fixture as `make e2e` (`tests/e2e/conftest.py`) and the `answer_all_transfer` helper:

```python
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from risk_trainer.storage.memory import MemoryAttemptStore
from risk_trainer.web.app import create_app
from tests.e2e.conftest import _serve
from tests.e2e.flows import answer_all_transfer
from tests.web_helpers import RT001_ID, rt001, settings

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

live = create_app(
    settings(session_cookie_secure=False), MemoryAttemptStore(), [rt001()], preview=False
)
draft = create_app(
    settings(session_cookie_secure=False),
    MemoryAttemptStore(),
    [rt001(status="draft")],
    preview=True,
)
live_gen, draft_gen = _serve(live), _serve(draft)
live_url, draft_url = next(live_gen), next(draft_gen)

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scheme in ("light", "dark"):
            context = browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme=scheme
            )
            page = context.new_page()

            page.goto(live_url + "/")
            expect(page.locator(".scenario-card")).to_be_visible()
            page.screenshot(path=OUT / f"home-{scheme}.png", full_page=True)

            page.goto(f"{live_url}/s/{RT001_ID}")
            answer_all_transfer(page)
            page.screenshot(path=OUT / f"exercise-{scheme}.png", full_page=True)

            page.get_by_role("button", name="Submit my answers").click()
            expect(page.locator("#score")).to_be_visible()
            page.screenshot(path=OUT / f"debrief-{scheme}.png", full_page=True)

            page.goto(draft_url + "/")
            expect(page.locator(".banner-draft, .banner-preview").first).to_be_visible()
            page.screenshot(path=OUT / f"preview-{scheme}.png", full_page=True)
            context.close()
        browser.close()
finally:
    for gen in (live_gen, draft_gen):
        next(gen, None)
```

Theme follows the emulated device scheme (Auto), so no `data-theme` is set. Captured 17 Nov 2026 with Chromium 153 (Playwright 1.63).

## Keeping this in sync

- Change a token in `app.css`: change `tokens.json` (value and usage note) and the table above in the same pull request. UI-04 fails otherwise.
- Change a component or the masthead: update the matching section and recapture the affected screens.
- Anything that alters learner-visible behavior also updates `docs/PRD.md` and names the requirement IDs ([AGENTS.md](../AGENTS.md)).
