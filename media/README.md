# Omni Steroid — real-product showcase media

Every asset here is the **current Omni Steroid app** (Daylight UI — wordmark
**Omni Steroid**, Home IA, evergreen accent) running end-to-end against the
**real Python engine** — never mock mode, never a generated/painted mock-up.
The demo video is **genuinely screen-recorded** by Playwright (`recordVideo`)
while a script drives the running app; it is not AI-generated.

## How it was captured (honest boundary)

- **Real engine.** A real `python -m engine.server` sidecar was booted on a
  temp SQLite DB seeded with synthetic (non-PII) meetings and a small Obsidian
  vault, indexed by the real BM25 indexer.
- **Real UI build.** Production Vite build served in headless Chromium with a
  thin shim over OS-native Tauri seams only (folder picker / tray).
- **Ask synthesis.** Live Gemini answers require `GEMINI_API_KEY`. Offline
  recapture may show the Ask shell mid-query without a finished answer —
  meeting detail still shows real enhanced notes and transcript from the seed.
- **Naomi.** Shown when Cartesia voice is configured; otherwise Voice notes
  history may be captured in that slot.

## Assets

| File | What it shows |
| --- | --- |
| `omni-demo.mp4` / `omni-demo.gif` | Recorded tour of Home → Meetings → detail → Ask → Settings → Voice notes |
| `screenshots/00-home.png` | Home dashboard — Record, dictate, Ask, import |
| `screenshots/01-library.png` | Meetings library with seeded rows |
| `screenshots/02-meeting-detail.png` | Enhanced notes + transcript for Northwind Renewal |
| `screenshots/03-ask-answer.png` | Ask canvas (query in flight / answer when keyed) |
| `screenshots/04-settings-router.png` … `05-…` | Settings shell |
| `screenshots/06-naomi-pool.png` | Voice notes / Naomi surface |
| `screenshots/07-onboarding-welcome.png` … `10-…` | First-run wizard (Welcome to Omni Steroid → models) |

Screenshots are captured at the 1440×900 design canvas at 2× (2880×1800).

## Re-capture

From `apps/ui` (needs local `.venv` and optional keys in `.env`):

```powershell
$env:OMNI_E2E_ALLOW_NO_KEYS = "1"   # omit when GEMINI_API_KEY is set for a full Ask answer
npx playwright test --config e2e/playwright.config.ts --project=media
```

Then convert the tour webm under `apps/ui/test-results/` with ffmpeg to
`media/omni-demo.mp4` + `media/omni-demo.gif`, and copy PNGs into
`assets/readme/daylight/` for the root README (new folder names bust GitHub Camo cache).
