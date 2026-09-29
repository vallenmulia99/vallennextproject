"""VALLEN CLI — Vision Analysis Tool (inspired by Hermes vision_analyze).

Enables the agent to inspect images, diagrams, UI screenshots, and visual bugs.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import resolve_workspace_path

_SUPPORTED_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class VisionAnalyzeTool(BaseTool):
    name = "vision_analyze"
    aliases = ["inspect_image", "analyze_image"]
    description = (
        "Inspect and analyze an image file (UI screenshot, diagram, error visual, design mock). "
        "Returns the image directly to the model with your analysis question."
    )
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local image file (relative to workspace or absolute)",
            },
            "question": {
                "type": "string",
                "description": "What specific details to examine or analyze in the image",
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [x1, y1, x2, y2] pixel coordinates to crop into specific detail",
            },
        },
        "required": ["image_path", "question"],
    }

    async def execute(
        self,
        image_path: str = "",
        question: str = "",
        region: list[int] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        img_target = image_path or kwargs.get("path", "")
        if not img_target:
            return ToolResult(success=False, output="", error="image_path is required")

        p = resolve_workspace_path(img_target)
        if not p.exists() or not p.is_file():
            return ToolResult(success=False, output="", error=f"Image file not found: {p}")

        ext = p.suffix.lower()
        mime = _SUPPORTED_EXTENSIONS.get(ext)
        if not mime:
            return ToolResult(
                success=False,
                output="",
                error=f"Unsupported image format '{ext}'. Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS.keys()))}",
            )

        raw_bytes = p.read_bytes()
        notice = ""

        # Crop region if requested and PIL is available
        if region and len(region) == 4:
            try:
                import io
                from PIL import Image
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    cropped = img.crop(tuple(region))
                    buf = io.BytesIO()
                    cropped.save(buf, format=img.format or "PNG")
                    raw_bytes = buf.getvalue()
                    notice = f" [Cropped to region {region}]"
            except ImportError:
                notice = " [Region crop requested but Pillow is not installed; using full image]"
            except Exception as e:
                notice = f" [Crop failed ({e}); using full image]"

        b64 = base64.b64encode(raw_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        summary = f"Loaded image {p.name} ({len(raw_bytes):,} bytes){notice}. Question: {question}"

        return ToolResult(
            success=True,
            output=summary,
            data=[
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": summary},
            ],
        )
