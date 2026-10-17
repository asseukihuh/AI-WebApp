# Creative brief (Phase B)

`POST /api/creative-brief` returns structured marketing decisions before `POST /api/generate-poster`. The LLM does not render pixels — `scripts/poster_compiler.py` maps the brief to PhotoCraft commands.

See [README](../README.md#creative-brief-llm-phase-b) for provider env vars and recommended frontier models.

## Response shape

```json
{
  "brief": {
    "headline": "…",
    "subhead": "…",
    "layoutRecipe": "photo-hero-type",
    "heroStrategy": "use_kit_photo",
    "logoTreatment": "wordmark-white",
    "emphasis": "calm",
    "rationale": "One sentence for the UI."
  },
  "source": "llm",
  "model": "claude-sonnet-5-5",
  "provider": "anthropic"
}
```

`source` is `fallback` when no API key is configured or the model call fails. Fallback responses include `fallbackReason` (`no_provider`, `no_api_key`, or `llm_error`) and `errorDetail` (short diagnostic, no secrets). On LLM errors, `provider` is included. Successful LLM responses include `model` and `provider`.

Anthropic defaults to `claude-sonnet-5-5` when `COMMMAKER_LLM_MODEL` is unset. For maximum reasoning, set `COMMMAKER_LLM_MODEL=claude-opus-4-8`. Dated Sonnet 4 / Opus 4 model ids (e.g. `claude-sonnet-4-20250514`) were retired on the Anthropic API; a 404 from Anthropic surfaces `errorDetail` hinting to check `COMMMAKER_LLM_MODEL`.

Anthropic Sonnet 5.5 / Opus 5.5 reject forced `tool_choice` (`{"type":"tool","name":"…"}`) with HTTP 400. The creative-brief client uses `tool_choice: auto`, `strict: true` on `submit_creative_brief`, and instructs the model to call that tool once; if the response has no `tool_use`, it retries once then falls back to parsing text JSON. On `llm_error`, `errorDetail` may include a truncated API response body (e.g. `HTTP 400: …`).
