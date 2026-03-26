"""HCaptcha solver using Playwright browser automation.

Supports ``HCaptchaTaskProxyless`` task type.

Strategy:
  1. Visit the target page with a realistic browser context.
  2. Click the hCaptcha checkbox.
  3. If a token is issued immediately, return it.
  4. If an image-selection challenge appears, extract the prompt + tile images,
     call ``ClassificationSolver`` for ``HCaptchaClassification``-style
     reasoning, click the matching tiles, submit the challenge, and continue
     polling for the token.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.async_api import Browser, ElementHandle, Frame, Page, Playwright, async_playwright

from ..core.config import Config
from .classification import ClassificationSolver

log = logging.getLogger(__name__)

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}};
"""

_EXTRACT_HCAPTCHA_TOKEN_JS = """
() => {
    const textarea = document.querySelector('[name="h-captcha-response"]')
        || document.querySelector('[name="g-recaptcha-response"]');
    if (textarea && textarea.value && textarea.value.length > 20) {
        return textarea.value;
    }
    if (window.hcaptcha && typeof window.hcaptcha.getResponse === 'function') {
        const resp = window.hcaptcha.getResponse();
        if (resp && resp.length > 20) return resp;
    }
    return null;
}
"""

_QUESTION_JS = """
() => {
    const prompt = document.querySelector('.prompt-text')
        || document.querySelector('h2.prompt-text')
        || document.querySelector('.challenge-prompt')
        || document.querySelector('[class*="prompt"]');
    return prompt?.textContent?.trim() || null;
}
"""

_CHALLENGE_TILE_SELECTORS = (
    ".task-grid .task-image",
    ".task-grid .task",
    ".task-grid .image",
    ".challenge-container .task-image",
    ".challenge-view .task-image",
    ".task-image",
    ".task",
)

_EXAMPLE_IMAGE_SELECTORS = (
    ".challenge-example .image",
    ".challenge-example",
    ".example-wrapper .image",
)

_VERIFY_BUTTON_SELECTORS = (
    ".button-submit",
    'button[type="submit"]',
    'button[aria-label*="Verify"]',
)


class HCaptchaSolver:
    """Solves ``HCaptchaTaskProxyless`` tasks via Playwright."""

    def __init__(
        self,
        config: Config,
        browser: Browser | None = None,
        classifier: ClassificationSolver | None = None,
    ) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = browser
        self._owns_browser = browser is None
        self._classifier = classifier

    async def start(self) -> None:
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.browser_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        log.info("HCaptchaSolver browser started")

    async def stop(self) -> None:
        if self._owns_browser:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        log.info("HCaptchaSolver stopped")

    async def solve(self, params: dict[str, Any]) -> dict[str, Any]:
        website_url = params["websiteURL"]
        website_key = params["websiteKey"]

        last_error: Exception | None = None
        for attempt in range(self._config.captcha_retries):
            try:
                token = await self._solve_once(website_url, website_key)
                return {"gRecaptchaResponse": token}
            except Exception as exc:
                last_error = exc
                log.warning(
                    "HCaptcha attempt %d/%d failed: %s",
                    attempt + 1,
                    self._config.captcha_retries,
                    exc,
                )
                if attempt < self._config.captcha_retries - 1:
                    await asyncio.sleep(2)

        raise RuntimeError(
            f"HCaptcha failed after {self._config.captcha_retries} attempts: {last_error}"
        )

    async def _solve_once(self, website_url: str, website_key: str) -> str:
        assert self._browser is not None
        target_url = self._prepare_target_url(website_url, website_key)
        if target_url != website_url:
            log.info("Normalized hCaptcha target URL to honor requested sitekey: %s", target_url)

        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = await context.new_page()
        await page.add_init_script(_STEALTH_JS)

        try:
            timeout_ms = self._config.browser_timeout * 1000
            await page.goto(target_url, wait_until="networkidle", timeout=timeout_ms)
            await page.mouse.move(400, 300)
            await asyncio.sleep(1)

            await self._click_checkbox(page)

            # 先给低风险会话一个直接出 token 的机会。
            token = await self._wait_for_token(page, seconds=4)
            if token:
                log.info("Got hCaptcha token directly after checkbox click (len=%d)", len(token))
                return token

            # 无头环境常见路径：进入图片 challenge，然后走 classification fallback。
            log.info(
                "No direct hCaptcha token after checkbox click, entering classification fallback"
            )
            fallback_handled = await self._solve_image_selection_challenge(page)
            if fallback_handled:
                token = await self._wait_for_token(page)

            if not isinstance(token, str) or len(token) < 20:
                raise RuntimeError(f"Invalid hCaptcha token: {token!r}")

            log.info("Got hCaptcha token (len=%d)", len(token))
            return token
        finally:
            await context.close()

    async def _click_checkbox(self, page: Page) -> None:
        frame = await self._find_frame(page, "checkbox", wait_seconds=10)
        if frame is None:
            raise RuntimeError("Could not find hCaptcha checkbox frame")

        checkbox = await frame.query_selector("#checkbox")
        if checkbox is None:
            raise RuntimeError("Could not find hCaptcha checkbox element")

        await checkbox.click(timeout=10_000)
        log.info("Clicked hCaptcha checkbox")

    async def _wait_for_token(self, page: Page, *, seconds: int | None = None) -> str | None:
        remaining = max(1, seconds or self._config.captcha_timeout)
        for _ in range(remaining):
            token = await page.evaluate(_EXTRACT_HCAPTCHA_TOKEN_JS)
            if isinstance(token, str) and len(token) > 20:
                return token
            await asyncio.sleep(1)
        return None

    async def _find_frame(
        self, page: Page, frame_role: str, *, wait_seconds: int = 5
    ) -> Frame | None:
        attempts = max(1, wait_seconds * 2)
        for _ in range(attempts):
            for frame in page.frames:
                url = frame.url or ""
                if "hcaptcha" in url and f"frame={frame_role}" in url:
                    return frame
            await asyncio.sleep(0.5)
        return None

    @staticmethod
    def _prepare_target_url(website_url: str, website_key: str) -> str:
        """为官方 demo 自动补齐/对齐 sitekey，确保按请求参数测试真实行为。"""
        if not website_key:
            return website_url

        parsed = urlsplit(website_url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        is_official_demo = host in {"accounts.hcaptcha.com", "demo.hcaptcha.com"} and path == "/demo"
        if not is_official_demo:
            return website_url

        query = parse_qs(parsed.query, keep_blank_values=True)
        changed = False

        current_sitekey = query.get("sitekey", [None])[0]
        if current_sitekey != website_key:
            query["sitekey"] = [website_key]
            changed = True

        if "hl" not in query:
            query["hl"] = ["en"]
            changed = True

        if not changed:
            return website_url

        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    async def _solve_image_selection_challenge(self, page: Page) -> bool:
        if self._classifier is None:
            raise RuntimeError(
                "Classification fallback is unavailable because no ClassificationSolver was injected"
            )

        rounds = max(1, self._config.captcha_retries)
        for round_index in range(rounds):
            token = await self._wait_for_token(page, seconds=1)
            if token:
                return True

            challenge = await self._collect_selection_challenge(page)
            if challenge is None:
                unsupported_reason = await self._describe_unsupported_challenge(page)
                log.warning(
                    "Could not collect hCaptcha image-selection challenge in round %d: %s",
                    round_index + 1,
                    unsupported_reason,
                )
                if round_index == 0:
                    raise RuntimeError(unsupported_reason)
                return False

            log.info(
                "Collected hCaptcha image-selection challenge in round %d: question=%r tiles=%d examples=%d",
                round_index + 1,
                challenge["question"],
                len(challenge["tiles"]),
                len(challenge["examples"]),
            )
            payload = self._build_classification_payload(
                question=challenge["question"],
                tile_images=challenge["tile_images"],
                examples=challenge["examples"],
            )
            result = await self._classifier.solve(payload)
            log.info("Classification solver returned raw result: %s", result)
            indices = self._extract_selection_indices(
                result=result,
                tile_count=len(challenge["tiles"]),
            )

            await self._click_selected_tiles(challenge["tiles"], indices)
            await self._click_verify_button(challenge["frame"])

            token = await self._wait_for_token(page, seconds=6)
            if token:
                return True

            log.info(
                "hCaptcha challenge round %d submitted without immediate token, retrying",
                round_index + 1,
            )

        return False

    async def _collect_selection_challenge(self, page: Page) -> dict[str, Any] | None:
        frame = await self._find_frame(page, "challenge", wait_seconds=10)
        if frame is None:
            return None

        await asyncio.sleep(1)
        question = await frame.evaluate(_QUESTION_JS)
        if not isinstance(question, str) or not question.strip():
            return None

        tiles = await self._find_clickable_tiles(frame)
        if not tiles:
            return None

        tile_entries: list[tuple[ElementHandle[Any], str]] = []
        for tile in tiles:
            encoded = await self._capture_element_base64(tile)
            if encoded:
                tile_entries.append((tile, encoded))

        if not tile_entries:
            return None

        return {
            "frame": frame,
            "question": question.strip(),
            "tiles": [tile for tile, _ in tile_entries],
            "tile_images": [encoded for _, encoded in tile_entries],
            "examples": await self._extract_example_images(frame),
        }

    async def _find_clickable_tiles(self, frame: Frame) -> list[ElementHandle[Any]]:
        for selector in _CHALLENGE_TILE_SELECTORS:
            elements = await frame.query_selector_all(selector)
            if elements:
                return elements
        return []

    async def _extract_example_images(self, frame: Frame) -> list[str]:
        examples: list[str] = []
        for selector in _EXAMPLE_IMAGE_SELECTORS:
            elements = await frame.query_selector_all(selector)
            if not elements:
                continue
            for element in elements:
                encoded = await self._capture_element_base64(element)
                if encoded:
                    examples.append(encoded)
            if examples:
                break
        return examples

    async def _describe_unsupported_challenge(self, page: Page) -> str:
        """给出更贴近真实 challenge 类型的错误信息，避免把 canvas/puzzle 误报成网格 DOM 问题。"""
        frame = await self._find_frame(page, "challenge", wait_seconds=2)
        if frame is None:
            return (
                "hCaptcha challenge iframe disappeared before the built-in fallback "
                "could inspect it"
            )

        prompt = await frame.evaluate(_QUESTION_JS)
        prompt_text = prompt.strip().lower() if isinstance(prompt, str) else ""
        has_canvas = await frame.locator("canvas").count() > 0
        submit_text = (
            await frame.locator(".button-submit").first.inner_text()
            if await frame.locator(".button-submit").count() > 0
            else ""
        )

        if "puzzle piece" in prompt_text or (has_canvas and "skip" in submit_text.lower()):
            log.warning(
                "Detected unsupported hCaptcha canvas/puzzle challenge: prompt=%r submit=%r has_canvas=%s",
                prompt,
                submit_text,
                has_canvas,
            )
            return (
                "hCaptcha presented a canvas/puzzle challenge, which is not supported "
                "by the built-in HCaptchaClassification fallback"
            )

        log.warning(
            "Detected unsupported hCaptcha challenge layout: prompt=%r submit=%r has_canvas=%s",
            prompt,
            submit_text,
            has_canvas,
        )
        return (
            "hCaptcha image challenge detected, but the current DOM layout is not "
            "supported by the built-in classification fallback"
        )

    async def _capture_element_base64(self, element: ElementHandle[Any]) -> str | None:
        try:
            image_bytes = await element.screenshot(type="png")
        except Exception:
            return None
        return base64.b64encode(image_bytes).decode("ascii")

    @staticmethod
    def _build_classification_payload(
        *, question: str, tile_images: list[str], examples: list[str]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "HCaptchaClassification",
            "question": question,
            "images": tile_images,
        }
        if examples:
            payload["examples"] = examples
        return payload

    @staticmethod
    def _extract_selection_indices(
        *, result: dict[str, Any], tile_count: int
    ) -> list[int]:
        raw_answer = result.get("answer")
        if isinstance(raw_answer, bool):
            indices = [0] if raw_answer and tile_count == 1 else []
        elif isinstance(raw_answer, list):
            indices = [int(idx) for idx in raw_answer if isinstance(idx, int | float)]
        else:
            raw_objects = result.get("objects")
            if isinstance(raw_objects, list):
                indices = [int(idx) for idx in raw_objects if isinstance(idx, int | float)]
            else:
                indices = []

        deduped: list[int] = []
        for idx in indices:
            if 0 <= idx < tile_count and idx not in deduped:
                deduped.append(idx)
        return deduped

    async def _click_selected_tiles(
        self,
        tiles: list[ElementHandle[Any]],
        indices: list[int],
    ) -> None:
        for idx in indices:
            await tiles[idx].click(timeout=10_000)
            await asyncio.sleep(0.2)
        log.info("Clicked %d hCaptcha tile(s): %s", len(indices), indices)

    async def _click_verify_button(self, frame: Frame) -> None:
        for selector in _VERIFY_BUTTON_SELECTORS:
            button = await frame.query_selector(selector)
            if button is None:
                continue
            await button.click(timeout=10_000)
            await asyncio.sleep(1)
            log.info("Submitted hCaptcha challenge with selector %s", selector)
            return
        raise RuntimeError("Could not find hCaptcha verify/submit button")
