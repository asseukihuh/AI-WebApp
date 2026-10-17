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
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic"
}
```

`source` is `fallback` when no API key is configured or the model call fails; `model` / `provider` are omitted on fallback.
