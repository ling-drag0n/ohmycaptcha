# hCaptcha Usage

hCaptcha presents a CAPTCHA challenge via an iframe widget. The solver visits the target page with a Playwright-controlled Chromium browser, clicks the hCaptcha checkbox, and extracts the `h-captcha-response` token.

If hCaptcha escalates to an image-selection challenge in headless mode, the built-in solver now:

1. extracts the challenge prompt and candidate tile images,
2. sends them through the `HCaptchaClassification` reasoning path,
3. clicks the predicted matching tiles inside the challenge iframe,
4. submits the challenge and continues polling for the token.

## Supported task type

| Task type | Description |
|-----------|-------------|
| `HCaptchaTaskProxyless` | Browser-based hCaptcha solving |

## Required fields

| Field | Type | Description |
|-------|------|-------------|
| `websiteURL` | string | Full URL of the page containing the captcha |
| `websiteKey` | string | The `data-sitekey` value from the page's HTML. For official demo URLs, the solver now auto-injects it into the demo query string so the requested test key is actually used. |

## Test targets

hCaptcha provides official test keys that produce predictable results:

| URL | Site key | Behavior |
|-----|----------|----------|
| `https://accounts.hcaptcha.com/demo` | `10000000-ffff-ffff-ffff-000000000001` | Always passes (test key) |
| `https://accounts.hcaptcha.com/demo` | `20000000-ffff-ffff-ffff-000000000002` | Enterprise safe-user test |
| `https://demo.hcaptcha.com/` | `10000000-ffff-ffff-ffff-000000000001` | Always passes (test key) |

!!! note "Official demo URL normalization"
    The official demo page supports `?sitekey=...` in the URL itself. If you send `websiteURL=https://accounts.hcaptcha.com/demo` together with a `websiteKey`, the solver now rewrites the target URL to `...?sitekey=<websiteKey>&hl=en` before opening the page, matching the documented demo behavior.

## Create a task

```bash
curl -X POST http://localhost:8000/createTask \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-client-key",
    "task": {
      "type": "HCaptchaTaskProxyless",
      "websiteURL": "https://accounts.hcaptcha.com/demo",
      "websiteKey": "10000000-ffff-ffff-ffff-000000000001"
    }
  }'
```

Response:

```json
{
  "errorId": 0,
  "taskId": "uuid-string"
}
```

## Poll for result

```bash
curl -X POST http://localhost:8000/getTaskResult \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-client-key",
    "taskId": "uuid-from-createTask"
  }'
```

When ready:

```json
{
  "errorId": 0,
  "status": "ready",
  "solution": {
    "gRecaptchaResponse": "P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
  }
}
```

!!! note "Response field name"
    The token is returned in `solution.gRecaptchaResponse` for YesCaptcha API compatibility, even though hCaptcha natively uses the `h-captcha-response` field name.

## Acceptance status

| Target | Site key | Status | Notes |
|--------|----------|--------|-------|
| `https://accounts.hcaptcha.com/demo` | `10000000-ffff-ffff-ffff-000000000001` | ✅ Verified | The solver now honors the requested demo sitekey and receives the official direct-pass token in headless mode |

### Headless browser note

If a real site escalates to an image-selection challenge in headless mode, the solver will attempt the built-in `HCaptchaClassification` fallback.

The built-in `HCaptchaTaskProxyless` solver now attempts an automatic `HCaptchaClassification` fallback for image-selection challenges before failing. Standalone `HCaptchaClassification` is still available when you want to classify extracted tiles yourself. See [Image Classification](classification.md) for details.

If hCaptcha instead presents a canvas / puzzle-piece challenge, the current fallback will stop with a specific unsupported-challenge error rather than misreporting it as a grid DOM extraction failure.

### Observability / how to tell whether classification really ran

When classification is triggered, the service log now emits lines like:

- `No direct hCaptcha token after checkbox click, entering classification fallback`
- `Collected hCaptcha image-selection challenge in round ...`
- `Classification request: task_type=HCaptchaClassification ...`
- `Classification raw response: ...`
- `Classification parsed result: ...`

If you only see `Got hCaptcha token directly after checkbox click`, the request was solved by the official test key path and no model-based image classification call was needed.

### Challenge families observed during real testing

Based on the official demo and current open-source solver research, the main runtime branches we observed are:

1. direct-pass / no visible challenge,
2. image-selection grid challenges (the branch handled by `HCaptchaClassification`),
3. canvas / puzzle-piece challenges (currently unsupported by this project),
4. accessibility-related branches exposed through the challenge menu.

The official public demo test key `10000000-ffff-ffff-ffff-000000000001` is excellent for service sanity checks, but it does **not** force the image-classification branch. At the time of writing, we did not find an official public URL that reliably forces the grid/image-selection branch on every run; use your own controlled hCaptcha integration if you need deterministic classification-path testing.

### Controlled local testing

The official hCaptcha docs add two important constraints for local testing:

1. `localhost` and `127.0.0.1` are not accepted hostnames for normal widget testing.
2. Public test keys are intended for integration sanity checks and always generate a passcode without forcing image-classification.

If you want to verify the `HCaptchaClassification` branch locally, the most reliable route is:

1. create your own hCaptcha sitekey for a test flow,
2. point a custom hostname (for example `test.mydomain.com`) to `127.0.0.1` in your hosts file,
3. serve a minimal local page that embeds your own sitekey,
4. for Enterprise, add a `Challenge` rule targeting your IP / user agent; for Pro / free, use a second sitekey set to `Always Challenge`,
5. run `HCaptchaTaskProxyless` against that controlled page URL and watch the classification logs.

!!! note "Challenge != guaranteed visual grid"
    hCaptcha's own docs explicitly say that `challenge` does not automatically mean `visual challenge`. In Pro / free mode you may still need several reloads before a visible challenge appears, even when the sitekey behavior is configured for `Always Challenge`.

## Image classification (HCaptchaClassification)

For programmatic grid classification without browser automation, see [Image Classification](classification.md).

## Operational notes

- hCaptcha challenges may require more time than reCAPTCHA v2 — the solver first checks for a direct token, then falls back to classification-driven tile clicking when a challenge iframe appears.
- Real-world sites with aggressive bot detection may require additional fingerprinting improvements.
- Test keys (`10000000-ffff-ffff-ffff-000000000001`) always pass and are useful for flow validation.
