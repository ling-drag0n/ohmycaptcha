"""Focused unit tests for the hCaptcha classification fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.core.config import Config
from src.services.hcaptcha import HCaptchaSolver


def _make_config() -> Config:
    return Config(
        server_host="127.0.0.1",
        server_port=8000,
        client_key=None,
        cloud_base_url="https://example.com/v1",
        cloud_api_key="cloud-key",
        cloud_model="gpt-5.4",
        local_base_url="https://example.com/v1",
        local_api_key="local-key",
        local_model="qwen",
        captcha_retries=3,
        captcha_timeout=5,
        browser_headless=True,
        browser_timeout=30,
    )


class _FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []

    async def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))


class _FakePage:
    def __init__(self) -> None:
        self.mouse = _FakeMouse()
        self.init_scripts: list[str] = []
        self.goto_calls: list[tuple[str, str, int]] = []
        self.frames: list[object] = []
        self.main_frame: object = object()

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append((url, wait_until, timeout))


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.context_kwargs: list[dict[str, object]] = []
        self.context = _FakeContext(page)

    async def new_context(self, **kwargs: object) -> _FakeContext:
        self.context_kwargs.append(kwargs)
        return self.context


class _FakeElement:
    def __init__(self) -> None:
        self.click_count = 0

    async def click(self, *, timeout: int) -> None:
        self.click_count += 1


class _FakeLocator:
    def __init__(self, count: int = 0) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _FakeFrame:
    def __init__(
        self,
        url: str,
        *,
        selectors: dict[str, object] | None = None,
        prompt: str | None = None,
        canvas_count: int = 0,
    ) -> None:
        self.url = url
        self._selectors = selectors or {}
        self._prompt = prompt
        self._canvas_count = canvas_count

    async def query_selector(self, selector: str) -> object | None:
        value = self._selectors.get(selector)
        if isinstance(value, list):
            return value[0] if value else None
        return value

    async def query_selector_all(self, selector: str) -> list[object]:
        value = self._selectors.get(selector)
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    async def evaluate(self, script: str) -> str | None:
        return self._prompt

    def locator(self, selector: str) -> _FakeLocator:
        if selector == "canvas":
            return _FakeLocator(self._canvas_count)
        return _FakeLocator(0)


def test_extract_selection_indices_accepts_answer_and_objects() -> None:
    assert HCaptchaSolver._extract_selection_indices(
        result={"answer": [0, 2, 2, 9, -1]},
        tile_count=4,
    ) == [0, 2]
    assert HCaptchaSolver._extract_selection_indices(
        result={"objects": [1, 3]},
        tile_count=4,
    ) == [1, 3]
    assert HCaptchaSolver._extract_selection_indices(
        result={"answer": True},
        tile_count=1,
    ) == [0]


def test_build_classification_payload_preserves_examples() -> None:
    payload = HCaptchaSolver._build_classification_payload(
        question="Please click each image containing a basket",
        tile_images=["tile-a", "tile-b"],
        examples=["example-a"],
    )

    assert payload["type"] == "HCaptchaClassification"
    assert payload["question"] == "Please click each image containing a basket"
    assert payload["images"] == ["tile-a", "tile-b"]
    assert payload["examples"] == ["example-a"]


def test_prepare_target_url_injects_sitekey_for_official_demo() -> None:
    url = HCaptchaSolver._prepare_target_url(
        "https://accounts.hcaptcha.com/demo",
        "10000000-ffff-ffff-ffff-000000000001",
    )

    assert (
        url
        == "https://accounts.hcaptcha.com/demo?sitekey=10000000-ffff-ffff-ffff-000000000001&hl=en"
    )


def test_prepare_target_url_keeps_non_demo_url_unchanged() -> None:
    url = HCaptchaSolver._prepare_target_url(
        "https://example.com/login",
        "10000000-ffff-ffff-ffff-000000000001",
    )

    assert url == "https://example.com/login"


def test_solve_once_uses_classification_fallback_when_checkbox_has_no_token() -> None:
    page = _FakePage()
    browser = _FakeBrowser(page)
    solver = HCaptchaSolver(
        config=_make_config(),
        browser=browser,
        classifier=AsyncMock(),
    )

    solver._click_checkbox = AsyncMock()  # type: ignore[method-assign]
    solver._wait_for_token = AsyncMock(side_effect=[None, "P1_valid_hcaptcha_token"])  # type: ignore[method-assign]
    solver._solve_image_selection_challenge = AsyncMock(return_value=True)  # type: ignore[method-assign]

    token = asyncio.run(solver._solve_once("https://example.com", "sitekey"))

    assert token == "P1_valid_hcaptcha_token"
    assert solver._click_checkbox.await_count == 1
    assert solver._solve_image_selection_challenge.await_count == 1
    assert browser.context.closed is True


def test_solve_once_skips_fallback_when_checkbox_returns_token_immediately() -> None:
    page = _FakePage()
    browser = _FakeBrowser(page)
    solver = HCaptchaSolver(
        config=_make_config(),
        browser=browser,
        classifier=AsyncMock(),
    )

    solver._click_checkbox = AsyncMock()  # type: ignore[method-assign]
    solver._wait_for_token = AsyncMock(return_value="P1_valid_hcaptcha_token")  # type: ignore[method-assign]
    solver._solve_image_selection_challenge = AsyncMock(return_value=True)  # type: ignore[method-assign]

    token = asyncio.run(solver._solve_once("https://example.com", "sitekey"))

    assert token == "P1_valid_hcaptcha_token"
    assert solver._click_checkbox.await_count == 1
    solver._solve_image_selection_challenge.assert_not_awaited()
    assert browser.context.closed is True


def test_solve_once_normalizes_official_demo_url_with_requested_sitekey() -> None:
    page = _FakePage()
    browser = _FakeBrowser(page)
    solver = HCaptchaSolver(
        config=_make_config(),
        browser=browser,
        classifier=AsyncMock(),
    )

    solver._click_checkbox = AsyncMock()  # type: ignore[method-assign]
    solver._wait_for_token = AsyncMock(return_value="P1_valid_hcaptcha_token")  # type: ignore[method-assign]
    solver._solve_image_selection_challenge = AsyncMock(return_value=True)  # type: ignore[method-assign]

    asyncio.run(
        solver._solve_once(
            "https://accounts.hcaptcha.com/demo",
            "10000000-ffff-ffff-ffff-000000000001",
        )
    )

    assert page.goto_calls == [
        (
            "https://accounts.hcaptcha.com/demo?sitekey=10000000-ffff-ffff-ffff-000000000001&hl=en",
            "networkidle",
            30000,
        )
    ]


def test_find_frame_accepts_stripe_checkbox_frame_without_frame_query() -> None:
    page = _FakePage()
    checkbox = _FakeElement()
    page.frames = [
        page.main_frame,
        _FakeFrame("https://js.stripe.com/v3/hcaptcha-invisible-abc.html"),
        _FakeFrame(
            "https://js.stripe.com/v3/hcaptcha-inner-abc.html",
            selectors={"#checkbox": checkbox},
        ),
    ]
    solver = HCaptchaSolver(config=_make_config(), browser=None, classifier=AsyncMock())

    frame = asyncio.run(solver._find_frame(page, "checkbox", wait_seconds=1))

    assert frame is page.frames[2]


def test_find_frame_accepts_hcaptcha_html_challenge_without_frame_query() -> None:
    page = _FakePage()
    challenge_tile = _FakeElement()
    page.frames = [
        page.main_frame,
        _FakeFrame(
            "https://newassets.hcaptcha.com/captcha/v1/demo/static/hcaptcha.html",
            selectors={".task-image": [challenge_tile]},
            prompt="Please click each image containing a basket",
        ),
    ]
    solver = HCaptchaSolver(config=_make_config(), browser=None, classifier=AsyncMock())

    frame = asyncio.run(solver._find_frame(page, "challenge", wait_seconds=1))

    assert frame is page.frames[1]


def test_click_checkbox_reports_available_frames_when_lookup_fails() -> None:
    page = _FakePage()
    page.frames = [
        page.main_frame,
        _FakeFrame("https://js.stripe.com/v3/hcaptcha-invisible-abc.html"),
    ]
    solver = HCaptchaSolver(config=_make_config(), browser=None, classifier=AsyncMock())

    try:
        asyncio.run(solver._click_checkbox(page))
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "Could not find hCaptcha checkbox element inside frame" in message
    assert "hcaptcha-invisible-abc.html" in message
