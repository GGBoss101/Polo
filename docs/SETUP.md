# Polo setup

How to get API keys, configure `.env`, run the prototype, and compare models. Free-tier details below were checked on 2026-11-01. They change often, so trust each provider's console over this page.

## 1. Install tools (once)

```sh
brew install uv          # Python + dependency manager; installs Python 3.11+ itself
cd ~/Documents/Polo
uv sync
cp .env.example .env     # .env is gitignored; never commit it
```

You only need one provider to start. The cheapest path is Ollama (free, local) or Gemini (free tier) for your own testing, and Claude for anything testers touch.

## 2. Get keys

| Provider | Cost | Key goes in | Good for |
|---|---|---|---|
| Ollama | Free, runs on your Mac | no key (`OLLAMA_URL`) | Unlimited local testing, evals |
| Google Gemini | Free tier, rate limited | `GEMINI_API_KEY` | Your own testing only |
| Groq | Free tier, rate limited | `GROQ_API_KEY` | Fast free vision model |
| OpenRouter | Free `:free` models, rate limited | `OPENROUTER_API_KEY` | Trying several open models |
| Anthropic (Claude) | Paid, prepaid credits | `ANTHROPIC_API_KEY` | The pilot and the accuracy baseline |

### Ollama (free, local)
1. Install the app from ollama.com (or `brew install ollama`) and open it. It runs in the menu bar.
2. Pull a vision model:
   - `ollama pull gemma3:4b` (about 3 GB, fine on an 8 GB Mac)
   - `ollama pull qwen2.5vl:7b` (about 6 GB, better on 16 GB or more)
   - Newer vision models appear at ollama.com/search?c=vision. Any model you pull shows up in the picker automatically.
3. Nothing to put in `.env` unless Ollama runs on another machine (`OLLAMA_URL`).

### Google Gemini (free tier)
1. Go to aistudio.google.com and sign in with a Google account.
2. Click **Get API key**, then **Create API key**. No card needed.
3. Paste it as `GEMINI_API_KEY`.
4. Your actual limits are at aistudio.google.com/rate-limit. Limits are per project, so extra keys in the same project don't add quota.
5. **Privacy:** on the free tier Google may use prompts and images to improve its products, and humans may review them. Use it for your own posters, not testers' photos.
6. `GEMINI_MODELS` defaults to `gemini-3.8-flash`. If AI Studio lists a different free Flash model for your project, change it there.

### Groq (free tier)
1. Go to console.groq.com and sign up.
2. Open **API Keys**, then **Create API Key**.
3. Paste it as `GROQ_API_KEY`.
4. `GROQ_MODELS` defaults to `qwen/qwen3.8-27b`, Groq's vision model with structured output support (max 3 images per request).

### OpenRouter (free models)
1. Go to openrouter.ai and sign in.
2. Open **Settings > Keys**, then **Create Key**.
3. Paste it as `OPENROUTER_API_KEY`.
4. Free models end in `:free`. Current vision ones include `google/gemma-4-31b-it:free` and `nvidia/nemotron-3.5-super-vl:free`. The list changes often, so check openrouter.ai/collections/free-models and edit `OPENROUTER_MODELS`.
5. Free models are capped (roughly 20 requests per minute and a small daily cap). If a free model errors about data policy, check openrouter.ai/settings/privacy, since some free endpoints log or train on inputs.

### Anthropic (Claude)
1. Go to console.anthropic.com and sign up.
2. Open **Billing** and buy credits. A $5 minimum is enough for the whole pilot on Haiku, and for a few hundred scans on Opus.
3. Open **Limits** and set a monthly spend limit so a bug can't run up a bill.
4. Open **API Keys**, then **Create Key**, and paste it as `ANTHROPIC_API_KEY`.
5. Rough cost per scan is $0.02 to $0.03 on `claude-opus-5-5` and under $0.001 on `claude-haiku-5-5`. The page shows the real cost of each scan in dev mode.

## 3. Run it

```sh
uv run pytest
uv run --env-file .env uvicorn polo_extract.api:app --reload --app-dir extraction
```

Open http://localhost:8000. With `POLO_DEV=1` you get a model picker above the Extract button. Models whose key is missing are greyed out.

- **Pick a model** to run one scan with it. The result shows the model, time and cost.
- **Compare all available models** runs the same poster through every model you have set up, side by side.

**On your phone:** add `--host 0.0.0.0` to the command, run `ipconfig getifaddr en0` to get your Mac's IP, and open `http://<ip>:8000` on the same Wi-Fi.

## 4. Compare models with the eval

```sh
uv run --env-file .env python -m polo_eval --labels eval/labels/examples.jsonl --model ollama:gemma3:4b
uv run --env-file .env python -m polo_eval --labels eval/labels/examples.jsonl --model gemini:gemini-3.8-flash
uv run --env-file .env python -m polo_eval --labels eval/labels/examples.jsonl --model claude-haiku-5-5
```

Each run writes `eval/runs/<time>-<model>/report.md`. Use `--workers 1` for free tiers so you don't hit rate limits.

## 5. Before testers use it

- Set `POLO_DEV=0` so testers can't switch models.
- Set `POLO_MODEL` to a Claude model. Testers' photos shouldn't go to free tiers that train on inputs.
- Keep `POLO_RATE_LIMIT_PER_HOUR` low and the Anthropic spend limit on.

## Troubleshooting

| Message | Fix |
|---|---|
| `set ANTHROPIC_API_KEY in .env` (or another key) | Add the key, then restart the server. `--env-file` is only read at startup. |
| `Ollama isn't running` | Open the Ollama app. |
| `model not downloaded, run: ollama pull ...` | Run that command. |
| `... rate limit hit` | Wait a minute, or pick another model. |
| `... returned output that doesn't match the schema` | That model can't follow the JSON format reliably. Try a larger one. |
| `... was rejected` | The key is wrong or revoked. Create a new one. |

If a key ever ends up in git or a screenshot, revoke it in that provider's console and make a new one.
