"""Image classification solvers for various captcha types.

Supports HCaptchaClassification, ReCaptchaV2Classification,
FunCaptchaClassification, and AwsClassification task types.

All classification tasks send images + question text to an OpenAI-compatible
vision model for analysis and return structured coordinate/index results.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI
from PIL import Image

from ..core.config import Config

log = logging.getLogger(__name__)

HCAPTCHA_SYSTEM_PROMPT = """\
You are an image classification assistant for HCaptcha challenges.

You may receive:
1. optional sample/example images that show the target object, and
2. one or more candidate captcha images that must be classified.

Determine which candidate images match the question or the sample images.

Return STRICT JSON only. No markdown, no extra text.

For single-image questions (is this image X?):
{"answer": true}  or  {"answer": false}

For multi-image selection questions:
{"answer": [0, 2, 5]}
where numbers are 0-indexed positions of matching candidate images.

Rules:
- Return ONLY the JSON object, nothing else.
- Use example images only as references; do not include them in the returned indices.
- Be precise with your classification.
"""

RECAPTCHA_V2_SYSTEM_PROMPT = """\
You are an image classification assistant for reCAPTCHA v2 challenges.
Given a question and a grid image (3x3 or 4x4), identify which cells match the question.

The image cells are numbered 0-8 (3x3) or 0-15 (4x4), left-to-right, top-to-bottom.

Return STRICT JSON only:
{"objects": [0, 3, 6]}
where numbers are 0-indexed positions of matching cells.

Rules:
- Return ONLY the JSON object, nothing else.
- If no cells match, return {"objects": []}.
"""

FUNCAPTCHA_SYSTEM_PROMPT = """\
You are an image classification assistant for FunCaptcha challenges.
Given a question and a grid image (typically 2x3 = 6 cells), identify which cell
is the correct answer.

Cells are numbered 0-5, left-to-right, top-to-bottom.

Return STRICT JSON only:
{"objects": [3]}
where the number is the 0-indexed position of the correct cell.

Rules:
- Return ONLY the JSON object, nothing else.
- Usually only one cell is correct.
"""

AWS_SYSTEM_PROMPT = """\
You are an image classification assistant for AWS CAPTCHA challenges.
Given a question and one or more images, identify the correct answer.

Return STRICT JSON only:
{"objects": [1]}
where the number is the 0-indexed position of the matching image.

Rules:
- Return ONLY the JSON object, nothing else.
"""


class ClassificationSolver:
    """Solves image classification captchas using a vision model."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.local_base_url,
            api_key=config.local_api_key,
        )

    async def solve(self, params: dict[str, Any]) -> dict[str, Any]:
        task_type = params.get("type", "")
        system_prompt = self._get_system_prompt(task_type)
        question = params.get("question", "") or params.get("queries", "")

        # Handle different image field names across task types
        images = self._extract_images(params)
        if not images:
            raise ValueError("No image data provided")

        examples = self._extract_examples(params)
        log.info(
            "Classification request: task_type=%s model=%s images=%d examples=%d question=%r",
            task_type or "unknown",
            self._config.captcha_multimodal_model,
            len(images),
            len(examples),
            question[:120] if isinstance(question, str) else question,
        )
        result = await self._classify(system_prompt, question, images, examples=examples)
        log.info("Classification parsed result: %s", result)
        return result

    @staticmethod
    def _get_system_prompt(task_type: str) -> str:
        prompts = {
            "HCaptchaClassification": HCAPTCHA_SYSTEM_PROMPT,
            "ReCaptchaV2Classification": RECAPTCHA_V2_SYSTEM_PROMPT,
            "FunCaptchaClassification": FUNCAPTCHA_SYSTEM_PROMPT,
            "AwsClassification": AWS_SYSTEM_PROMPT,
        }
        return prompts.get(task_type, RECAPTCHA_V2_SYSTEM_PROMPT)

    @staticmethod
    def _extract_images(params: dict[str, Any]) -> list[str]:
        """Extract base64 image(s) from various param formats."""
        images: list[str] = []

        if "image" in params:
            images.append(params["image"])

        if "images" in params:
            imgs = params["images"]
            if isinstance(imgs, list):
                images.extend(imgs)
            elif isinstance(imgs, str):
                images.append(imgs)

        if "body" in params and not images:
            images.append(params["body"])

        # HCaptcha queries format: list of base64 strings
        if "queries" in params and isinstance(params["queries"], list):
            images.extend(params["queries"])

        return images

    @staticmethod
    def _extract_examples(params: dict[str, Any]) -> list[str]:
        examples = params.get("examples")
        if isinstance(examples, list):
            return [item for item in examples if isinstance(item, str)]
        if isinstance(examples, str):
            return [examples]
        return []

    @staticmethod
    def _prepare_image(b64_data: str) -> str:
        """Ensure image is properly formatted as a data URL."""
        if b64_data.startswith("data:image"):
            return b64_data
        try:
            img_bytes = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_bytes))
            fmt = img.format or "PNG"
            mime = f"image/{fmt.lower()}"
            return f"data:{mime};base64,{b64_data}"
        except Exception:
            return f"data:image/png;base64,{b64_data}"

    async def _classify(
        self,
        system_prompt: str,
        question: str,
        images: list[str],
        *,
        examples: list[str] | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []

        prepared_examples = examples or []
        if prepared_examples:
            content.append(
                {
                    "type": "text",
                    "text": (
                        "Sample images showing the target object. "
                        "Do not classify these; use them only as references."
                    ),
                }
            )
        for example_b64 in prepared_examples:
            data_url = self._prepare_image(example_b64)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"},
                }
            )

        if len(images) > 1:
            content.append(
                {
                    "type": "text",
                    "text": (
                        "Candidate images to classify. "
                        "Indices are 0-based in display order."
                    ),
                }
            )

        for img_b64 in images:
            data_url = self._prepare_image(img_b64)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"},
                }
            )

        user_text = question if question else "Classify this captcha image."
        content.append({"type": "text", "text": user_text})

        last_error: Exception | None = None
        for attempt in range(self._config.captcha_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=self._config.captcha_multimodal_model,
                    temperature=0.05,
                    max_tokens=512,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                )
                raw = response.choices[0].message.content or ""
                log.info("Classification raw response: %s", raw[:300])
                return self._parse_json(raw)
            except Exception as exc:
                last_error = exc
                log.warning("Classification attempt %d failed: %s", attempt + 1, exc)

        raise RuntimeError(
            f"Classification failed after {self._config.captcha_retries} attempts: {last_error}"
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        cleaned = match.group(1) if match else text.strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
        return data
