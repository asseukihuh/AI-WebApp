# Run CommMaker locally

**Repo:** [asseukihuh/AI-WebApp](https://github.com/asseukihuh/AI-WebApp)

## Windows (recommended)

```powershell
git clone https://github.com/asseukihuh/AI-WebApp.git
cd AI-WebApp
git pull
.\scripts\dev-commmaker.ps1
```

Open **http://localhost:8000/home.html** → Onboard → Crisis → Editor.

`dev-commmaker.ps1` loads **`.env`** from the repo root into the process environment, then starts `python scripts\serve-static.py`.

### `.env` and API keys

Create `.env` in the repo root (see `.env.example`):

```env
ANTHROPIC_API_KEY=sk-ant-usr-...
IDEOGRAM_API_KEY=...
```

Optional: `ANTHROPIC_WORKSPACE_ID`, `COMMMAKER_LLM_PROVIDER`, `COMMMAKER_LLM_MODEL`.

Keys are not committed; keep `.env` out of git.

### Verify keys without exposing secrets

1. **Server stderr** on start (when `ANTHROPIC_API_KEY` is set):

   `CommMaker: ANTHROPIC_API_KEY loaded (len=N, prefix=sk-ant-usr-…)`

2. **HTTP check** while the dev server is running:

   ```powershell
   curl.exe http://localhost:8000/api/dev-status
   ```

   Example response:

   ```json
   {
     "anthropicKeyLoaded": true,
     "anthropicKeyLen": 108,
     "ideogramKeyLoaded": true,
     "creativeBriefStack": "v24"
   }
   ```

   `anthropicKeyLen` should match your key length (Console `sk-ant-usr-…` keys are typically ~100+ characters). If `anthropicKeyLoaded` is false, the server never received a usable key.

## UTF-8 BOM on Windows (Notepad)

If you save `.env` with **Notepad → Save as → UTF-8**, Windows may write a **UTF-8 BOM** at the start of the file. The first variable name can become `\ufeffANTHROPIC_API_KEY` instead of `ANTHROPIC_API_KEY`, so Python never sees the key and Anthropic calls fail.

**Symptoms**

- `GET /api/dev-status` shows `anthropicKeyLoaded: false` even though `.env` looks correct.
- Creative brief falls back with `no_api_key`.
- Anthropic **401** `invalid x-api-key` when a mangled key is sent.

**Fixes**

1. Use **VS Code**, **Notepad++**, or PowerShell to save `.env` as **UTF-8 without BOM**.
2. Re-save with PowerShell (no BOM):

   ```powershell
   @"
   ANTHROPIC_API_KEY=sk-ant-usr-your-key-here
   IDEOGRAM_API_KEY=your-ideogram-key
   "@ | Set-Content -Path .env -Encoding utf8NoBOM
   ```

   On older PowerShell, use `utf8` and rely on `dev-commmaker.ps1` (PR **#25**+) which strips BOM from lines and variable names when loading `.env`.

3. Restart `.\scripts\dev-commmaker.ps1` after editing `.env`.

## Anthropic 401 `invalid x-api-key` checklist

Stack on **main** after PR **#24** (Console `sk-ant-usr-…` keys: `x-api-key` + `Authorization: Bearer`, optional `ANTHROPIC_WORKSPACE_ID`).

| Check | Action |
|-------|--------|
| Key loaded? | `GET /api/dev-status` → `anthropicKeyLoaded` true, `anthropicKeyLen` > 0 |
| BOM / whitespace | Re-save `.env` without BOM; no quotes around the key unless intentional |
| Console key type | Use a **Console** user key (`sk-ant-usr-…`), not an old-only format without Bearer support |
| Workspace | If Anthropic Console shows multiple workspaces, set `ANTHROPIC_WORKSPACE_ID` in `.env` |
| Session vs file | Prefer `.env` + `dev-commmaker.ps1`; `$env:ANTHROPIC_API_KEY` in the same window overrides nothing if `.env` loads first |
| Provider override | Unset `COMMMAKER_LLM_PROVIDER` or set `anthropic` when using Anthropic |
| Still 401 | Rotate key in Console; confirm `git pull` includes #24+ creative-brief auth headers |

Brief errors surface in the crisis UI (`fallbackReason`, `errorDetail`); server logs do not print full keys.

## macOS / Linux

```bash
export ANTHROPIC_API_KEY=sk-ant-usr-...
export IDEOGRAM_API_KEY=...
python3 scripts/serve-static.py --port 8000
```

Or use a `.env` loader of your choice; the static server does not read `.env` on Unix unless you export variables yourself.

## Related

- [Creative brief](creative-brief.md)
- [README](../README.md) — full env var table
