# FreeToken Local LLM Provider Setup Guide

CareerOS supports [FreeToken](https://github.com/FlashML-org/FreeToken) as an optional high-speed local inference provider alongside the default local Mistral (Ollama) setup.

---

## 1. Overview & Architecture

CareerOS uses a 3-tier fallback hierarchy:
1. **FreeToken (Local Primary)**: When `FREETOKEN_ENABLED=true` and healthy.
2. **Mistral / Ollama (Local Secondary)**: Default working local provider. Used automatically when FreeToken is disabled, offline, or returns an error.
3. **Gemini Flash (Cloud Fallback)**: Used when `GEMINI_API_KEY` is configured and local inference fails or times out.

> [!IMPORTANT]
> **Safety Rules Preserved**:
> Deterministic application safety checks ([submission_guard.py](file:///d:/1%20-%20Projects/Projects/CareerOS/CareerOS/apps/api/app/services/application_assistant/submission_guard.py)) and schema validations run on all model outputs regardless of which provider generated them. The automation will never click final submission buttons without deterministic safety clearance.

---

## 2. Launching FreeToken

FreeToken exposes an OpenAI-compatible API running locally on port `1919`.

### Launch the Server

Run `ft serve` pointing to your local model weights or Hugging Face model repository:

```bash
ft serve --model ~/models/Qwen3.6-35B-A3B
```

The server is ready when the output displays:
```text
API server is ready to serve on 127.0.0.1:1919
```

### Verify FreeToken Endpoint

Check that the server is serving models:

```bash
curl http://127.0.0.1:1919/v1/models
```

Send a test chat completion:

```bash
curl http://127.0.0.1:1919/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.6-35B-A3B",
    "messages": [{"role": "user", "content": "What is a Mixture-of-Experts model?"}],
    "max_tokens": 128
  }'
```

---

## 3. CareerOS Configuration

Enable FreeToken in your `.env` file (`CareerOS/.env` or `apps/api/.env`):

```env
# FreeToken local provider
FREETOKEN_ENABLED=true
FREETOKEN_BASE_URL=http://127.0.0.1:1919/v1
FREETOKEN_MODEL=Qwen3.6-35B-A3B
FREETOKEN_TIMEOUT=60
FREETOKEN_API_KEY=
```

### Configurable Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `FREETOKEN_ENABLED` | `false` | Enable/disable FreeToken as primary local provider. |
| `FREETOKEN_BASE_URL` | `http://127.0.0.1:1919/v1` | Base URL of FreeToken OpenAI-compatible endpoint. |
| `FREETOKEN_MODEL` | `Qwen3.6-35B-A3B` | Model name or Hugging Face repo served by FreeToken. |
| `FREETOKEN_TIMEOUT` | `60` | HTTP request timeout in seconds. |
| `FREETOKEN_API_KEY` | *(empty)* | Optional API key (if reverse-proxied or auth-protected). |

---

## 4. Health Checking & Failover

CareerOS performs non-blocking health checks before dispatching requests to FreeToken:
- Probes `GET {base_url}/models` with a fast 1.5-second timeout.
- Caches health status with a 5-second TTL to avoid endpoint hammering.
- If FreeToken is offline or unreachable, CareerOS immediately logs a warning and routes the request directly to local Mistral (Ollama), preventing 60-second timeouts or navigation failures.
- All calls record the active provider (`freetoken`, `ollama`, or `gemini`) and latency in `model_usage_event` for analytics.

---

## 5. Benchmarking & Performance Comparison

A comparison CLI tool is provided to test Mistral and FreeToken against representative CareerOS application prompts:

```bash
cd apps/api
python scripts/compare_mistral_freetoken.py
```

To run with simulated responses (verifying metrics calculation without live servers):

```bash
python scripts/compare_mistral_freetoken.py --mock
```

The script evaluates:
- **Latency (ms)**: Round-trip execution time.
- **Valid JSON Rate (%)**: Structured parsing success rate.
- **Answer Completeness (%)**: Presence of all required schema fields (`classification`, `answer`, `confidence`, `safeToSubmit`, `reasoning`).
- **Average Confidence**: Model-reported decision confidence.
- **Error Count**: Network, timeout, or validation errors.
