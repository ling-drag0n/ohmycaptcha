# Acceptance

This page documents acceptance targets for each supported captcha type, including the test URLs, site keys, and observed outcomes during local validation runs.

## Summary

| Captcha type | Target | Status |
|-------------|--------|--------|
| reCAPTCHA v3 | `https://antcpt.com/score_detector/` | ✅ Token returned |
| Cloudflare Turnstile | `https://react-turnstile.vercel.app/basic` | ✅ Dummy token returned |
| reCAPTCHA v2 | `https://www.google.com/recaptcha/api2/demo` | ⚠️ Requires audio challenge (see notes) |
| hCaptcha | `https://accounts.hcaptcha.com/demo` | ✅ Official test key direct-pass |
| Image-to-Text | Local base64 image | ✅ Text returned via vision model |
| Classification | Local base64 grid | ✅ Object indices returned via vision model |

---

## reCAPTCHA v3 — Primary acceptance target

**URL:** `https://antcpt.com/score_detector/`  
**Site key:** `6LcR_okUAAAAAPYrPe-HK_0RULO1aZM15ENyM-Mf`

### Acceptance checklist

1. Install dependencies and Playwright Chromium.
2. Start the service: `python main.py`
3. Confirm `GET /api/v1/health` returns all 19 supported types.
4. Create a `RecaptchaV3TaskProxyless` task.
5. Poll `POST /getTaskResult` until `status=ready`.
6. Confirm a non-empty `solution.gRecaptchaResponse`.

### Curl example

```bash
TASK=$(curl -s -X POST http://localhost:8000/createTask \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-key",
    "task": {
      "type": "RecaptchaV3TaskProxyless",
      "websiteURL": "https://antcpt.com/score_detector/",
      "websiteKey": "6LcR_okUAAAAAPYrPe-HK_0RULO1aZM15ENyM-Mf",
      "pageAction": "homepage"
    }
  }' | python -c "import sys,json; print(json.load(sys.stdin)['taskId'])")

curl -s -X POST http://localhost:8000/getTaskResult \
  -H "Content-Type: application/json" \
  -d '{"clientKey":"your-key","taskId":"'"$TASK"'"}'
```

### Verified outcome

- Service startup: ✅
- Health endpoint: ✅ (19 types registered)
- Task creation: ✅
- Token returned: ✅ (non-empty `gRecaptchaResponse`, length ~1060 chars)

---

## Cloudflare Turnstile

**URL:** `https://react-turnstile.vercel.app/basic`  
**Site key:** `1x00000000000000000000AA` (Cloudflare official test key — always passes)

### Curl example

```bash
curl -s -X POST http://localhost:8000/createTask \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-key",
    "task": {
      "type": "TurnstileTaskProxyless",
      "websiteURL": "https://react-turnstile.vercel.app/basic",
      "websiteKey": "1x00000000000000000000AA"
    }
  }'
```

### Verified outcome

- Token returned: ✅ `XXXX.DUMMY.TOKEN.XXXX` (expected for Cloudflare test sitekeys)

---

## reCAPTCHA v2

**URL:** `https://www.google.com/recaptcha/api2/demo`  
**Site key:** `6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-`

### Behavior with headless Chromium

Headless browsers are detected by Google's risk analysis engine. The checkbox click succeeds, but a visual image challenge is presented rather than issuing a token immediately.

**Implemented mitigation:** The solver falls back to the **audio challenge path** — clicking the audio button in the challenge dialog, downloading the MP3, transcribing via the configured model, and submitting the transcript.

!!! note "Audio challenge transcription"
    The audio challenge requires a language model capable of processing audio or base64-encoded audio data. Accuracy depends on the model endpoint configured via `CAPTCHA_MODEL`.

### Curl example

```bash
curl -s -X POST http://localhost:8000/createTask \
  -H "Content-Type: application/json" \
  -d '{
    "clientKey": "your-key",
    "task": {
      "type": "NoCaptchaTaskProxyless",
      "websiteURL": "https://www.google.com/recaptcha/api2/demo",
      "websiteKey": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-"
    }
  }'
```

### Status

⚠️ Functionally implemented with audio challenge fallback. Success rate depends on model audio capability and Google's current challenge difficulty.

---

## hCaptcha

**URL:** `https://accounts.hcaptcha.com/demo`  
**Site key:** `10000000-ffff-ffff-ffff-000000000001` (hCaptcha official test key)

### Behavior

The hCaptcha solver now normalizes the official demo URL so that the requested
`websiteKey` is actually injected as `?sitekey=...&hl=en` before navigation.
With the official public test key (`10000000-ffff-ffff-ffff-000000000001`), the
demo returns the documented direct-pass token in headless mode.

We also tested the default public demo widget sitekey
(`a5f74b19-9e45-40e0-b45d-47ff91b7a6c2`) and observed a different runtime
branch: a canvas / puzzle challenge with prompt
`Place the correct puzzle piece into the correct slot to complete the image`.
That branch is currently outside this project's built-in
`HCaptchaClassification` grid fallback.

### Status

✅ Verified sanity path with the official public test key:

- `createTask` succeeded for `HCaptchaTaskProxyless`
- `getTaskResult` returned
  `solution.gRecaptchaResponse=10000000-aaaa-bbbb-cccc-000000000001`
- service logs showed `Got hCaptcha token directly after checkbox click`

⚠️ We still do **not** have a public official URL that deterministically forces
the grid / image-selection branch on every run. For deterministic
classification-path testing, use your own controlled hCaptcha integration page
and sitekey. See [hCaptcha usage](usage/hcaptcha.md).

---

## Image-to-Text

Any base64-encoded image can be sent to `ImageToTextTask`. The vision model returns a structured description suitable for click/slide/drag_match captcha automation.

### Status

✅ Works with any OpenAI-compatible vision model endpoint. Accuracy depends on model capability.

---

## What these results mean

- ✅ **reCAPTCHA v3** and **Turnstile** are fully functional and pass in every local test run.
- ⚠️ **reCAPTCHA v2** browser-based solving is still limited by headless browser detection, and **hCaptcha** still has unsupported public branches such as canvas / puzzle challenges. Deterministic hCaptcha grid-path testing currently requires a controlled sitekey/page rather than the public demo.
- The service is designed as a **backend solver for flow2api** — in practice, real-world integrations extract the image challenge frames and send them to the classification endpoint, rather than relying on full browser automation to pass the widget.
