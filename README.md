# CommMaker

CommMaker turns a website into a brand kit, then into an editable LinkedIn poster in [PhotoCraft](https://github.com/storytold/photocraft).

Paste a site URL on **Onboard**. CommMaker builds a brand profile and a communication kit (colour, type, logo, graphic direction). On **Crisis**, a short brief becomes a LinkedIn caption and a **1200×627** poster. **Generate poster** writes a `.pcraft` and opens it in the embedded PhotoCraft editor, so the type and layers stay editable.

Clone this repository:

```bash
git clone https://github.com/asseukihuh/AI-WebApp.git
cd AI-WebApp
```

## Run locally (Windows)

[Python 3.11+](https://www.python.org/downloads/) on `PATH`, and [Git for Windows](https://git-scm.com/download/win).

Copy `.env.example` to `.env` in the repo root and set the keys you have:

```env
ANTHROPIC_API_KEY=
IDEOGRAM_API_KEY=
```

`ANTHROPIC_API_KEY` is the brand profile, communication kit, and poster brief. `IDEOGRAM_API_KEY` paints the poster field. Optional names are listed in `.env.example`.

```powershell
.\scripts\dev-commmaker.ps1
```

That script loads `.env`, installs the PhotoCraft web editor into `vendor/photocraft-web/`, and starts the dev server. Open **http://localhost:8000/**.

| Step | URL |
|------|-----|
| Home | http://localhost:8000/home.html |
| Onboard (website → kit) | http://localhost:8000/onboard.html |
| Crisis (brief → poster) | http://localhost:8000/crisis.html |
| PhotoCraft editor | http://localhost:8000/photocraft/ |

If a key does not load, see [docs/run-commmaker-locally.md](docs/run-commmaker-locally.md).

## Playwright

Onboard screenshots the site (desktop, full page, mobile) before the brand pass. Install Playwright and Chromium once:

```bash
pip install playwright pillow
python -m playwright install chromium
```

Without them, the kit is built from the static page only, and poster generation reports that screenshots were skipped.

## macOS and Linux

Export the same keys (the Python server does not read `.env` itself), install the editor, then start the server:

```bash
export ANTHROPIC_API_KEY=...
export IDEOGRAM_API_KEY=...
./scripts/fetch-photocraft-web.sh
python3 scripts/serve-static.py --port 8000
```

PhotoCraft does not need `Cross-Origin-Opener-Policy` or `Cross-Origin-Embedder-Policy`. `python3 scripts/serve-static.py --coop-coep` turns those headers on if something else requires them.

## Docs

- [Run locally](docs/run-commmaker-locally.md) — `.env`, key checks, Windows UTF-8 BOM
- [Brand profile](docs/brand-profile.md)
- [Communication kit](docs/communication-kit-spec.md)
- [Creative brief](docs/creative-brief.md)
- [Poster design](docs/poster-design-system.md)
- [Ideogram layers](docs/ideogram-layers.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
