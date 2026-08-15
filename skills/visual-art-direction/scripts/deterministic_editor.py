"""Deterministic, non-destructive image editing using Pillow.

First version covers:
- L1: exposure, contrast, saturation
- L2: explicit box crop, resize for media
- L3: bounded local exposure, contrast, and saturation adjustment

Does NOT do:
- Face detection
- Face reconstruction
- Background generation
- New person generation
- Generative L3/L4 operations
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .contracts import AdapterHealth, Capability, EditOperation, EditRequest, EditResult
from .evidence import sha256_file

# Parameter boundaries
EXPOSURE_MIN, EXPOSURE_MAX = -1.0, 1.0
CONTRAST_MIN, CONTRAST_MAX = 0.5, 1.5
SATURATION_MIN, SATURATION_MAX = 0.5, 1.5
MAX_DIMENSION = 8192


class DeterministicEditorAdapter:
    """Explicit adapter declaration for the bounded Pillow editor."""

    name = "deterministic-pillow"
    version = "1.0.0"

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities={Capability.V2_IMAGE_EDITING},
            evidence="Pillow deterministic L1/L2 and bounded local L3 editor is available",
        )

    def capabilities(self) -> set[Capability]:
        return {Capability.V2_IMAGE_EDITING}

    def edit(self, request: EditRequest) -> EditResult:
        if request.operation == EditOperation.EXPOSURE_CONTRAST_COLOR:
            return edit_l1(
                request.input_image,
                request.output_image,
                exposure=request.parameters.get("exposure", 0.0),
                contrast=request.parameters.get("contrast", 1.0),
                saturation=request.parameters.get("saturation", 1.0),
            )
        if request.operation == EditOperation.LOCAL_ADJUSTMENT:
            box = request.parameters.get("box")
            if not box or len(box) != 4:
                return EditResult(
                    success=False,
                    operation=request.operation,
                    parameters=request.parameters,
                    error="Local adjustment requires 'box' parameter with 4 elements",
                )
            return local_adjustment_l3(
                request.input_image,
                request.output_image,
                box=tuple(box),
                exposure=request.parameters.get("exposure", 0.0),
                contrast=request.parameters.get("contrast", 1.0),
                saturation=request.parameters.get("saturation", 1.0),
                feather=request.parameters.get("feather", 0),
            )
        if request.operation == EditOperation.CROP:
            box = request.parameters.get("box")
            if not box or len(box) != 4:
                return EditResult(
                    success=False,
                    operation=request.operation,
                    parameters=request.parameters,
                    error="Crop requires 'box' parameter with 4 elements",
                )
            return crop_l2(request.input_image, request.output_image, box=tuple(box))
        if request.operation == EditOperation.RESIZE:
            width = request.parameters.get("width")
            height = request.parameters.get("height")
            if not width or not height:
                return EditResult(
                    success=False,
                    operation=request.operation,
                    parameters=request.parameters,
                    error="Resize requires 'width' and 'height' parameters",
                )
            return resize_for_media(
                request.input_image,
                request.output_image,
                width=int(width),
                height=int(height),
                fit=request.parameters.get("fit", "contain"),
            )
        return EditResult(
            success=False,
            operation=request.operation,
            parameters=request.parameters,
            error=f"Unsupported operation: {request.operation}",
        )


def _validate_input_output(input_path: Path, output_path: Path) -> str:
    """Validate input/output paths.

    Returns:
        Error message or empty string if valid.
    """
    if not input_path.exists():
        return f"Input file does not exist: {input_path}"

    if not input_path.is_file():
        return f"Input path is not a file: {input_path}"

    if input_path.resolve() == output_path.resolve():
        return "Output path must differ from input path"

    if output_path.exists():
        try:
            if os.path.samefile(input_path, output_path):
                return "Input and output resolve to the same file"
        except OSError as exc:
            return f"Cannot verify output file identity: {exc}"

    return ""


def _save_png_atomic(image: Image.Image, output_path: Path) -> None:
    """Write a PNG completely before replacing the destination entry."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
    try:
        image.save(temporary_path, "PNG")
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_exposure(value: float) -> str:
    """Validate exposure parameter."""
    if not (EXPOSURE_MIN <= value <= EXPOSURE_MAX):
        return f"Exposure must be between {EXPOSURE_MIN} and {EXPOSURE_MAX}"
    return ""


def _validate_contrast(value: float) -> str:
    """Validate contrast parameter."""
    if not (CONTRAST_MIN <= value <= CONTRAST_MAX):
        return f"Contrast must be between {CONTRAST_MIN} and {CONTRAST_MAX}"
    return ""


def _validate_saturation(value: float) -> str:
    """Validate saturation parameter."""
    if not (SATURATION_MIN <= value <= SATURATION_MAX):
        return f"Saturation must be between {SATURATION_MIN} and {SATURATION_MAX}"
    return ""


def edit_l1(
    input_path: Path,
    output_path: Path,
    *,
    exposure: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> EditResult:
    """Apply L1 edits: exposure, contrast, saturation.

    Args:
        input_path: Path to input image.
        output_path: Path to output image.
        exposure: Exposure adjustment (-1.0 to 1.0).
        contrast: Contrast multiplier (0.5 to 1.5).
        saturation: Saturation multiplier (0.5 to 1.5).

    Returns:
        EditResult with operation details.
    """
    start_time = time.time()

    # Validate paths
    error = _validate_input_output(input_path, output_path)
    if error:
        return EditResult(
            success=False,
            operation=EditOperation.EXPOSURE_CONTRAST_COLOR,
            parameters={"exposure": exposure, "contrast": contrast, "saturation": saturation},
            error=error,
        )

    # Validate parameters
    for _param_name, param_value, validator in [
        ("exposure", exposure, _validate_exposure),
        ("contrast", contrast, _validate_contrast),
        ("saturation", saturation, _validate_saturation),
    ]:
        error = validator(param_value)
        if error:
            return EditResult(
                success=False,
                operation=EditOperation.EXPOSURE_CONTRAST_COLOR,
                parameters={"exposure": exposure, "contrast": contrast, "saturation": saturation},
                error=error,
            )

    input_hash = sha256_file(input_path)

    try:
        with Image.open(input_path) as img:
            img = img.convert("RGB")

            # Apply exposure (brightness adjustment)
            if exposure != 0.0:
                enhancer = ImageEnhance.Brightness(img)
                # Map -1..1 to 0..2 factor
                factor = 1.0 + exposure
                factor = max(0.0, min(2.0, factor))
                img = enhancer.enhance(factor)

            # Apply contrast
            if contrast != 1.0:
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(contrast)

            # Apply saturation
            if saturation != 1.0:
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(saturation)

            _save_png_atomic(img, output_path)

    except Exception as e:
        return EditResult(
            success=False,
            operation=EditOperation.EXPOSURE_CONTRAST_COLOR,
            parameters={"exposure": exposure, "contrast": contrast, "saturation": saturation},
            input_sha256=input_hash,
            error=str(e),
        )

    output_hash = sha256_file(output_path)
    with Image.open(output_path) as img:
        output_size = img.size

    elapsed = (time.time() - start_time) * 1000

    return EditResult(
        success=True,
        operation=EditOperation.EXPOSURE_CONTRAST_COLOR,
        parameters={"exposure": exposure, "contrast": contrast, "saturation": saturation},
        input_sha256=input_hash,
        output_sha256=output_hash,
        output_size=output_size,
        execution_time_ms=elapsed,
    )


def crop_l2(
    input_path: Path,
    output_path: Path,
    *,
    box: tuple[int, int, int, int],
) -> EditResult:
    """Apply L2 crop with explicit box.

    Args:
        input_path: Path to input image.
        output_path: Path to output image.
        box: Crop box as (left, upper, right, lower).

    Returns:
        EditResult with operation details.
    """
    start_time = time.time()

    # Validate paths
    error = _validate_input_output(input_path, output_path)
    if error:
        return EditResult(
            success=False,
            operation=EditOperation.CROP,
            parameters={"box": box},
            error=error,
        )

    # Validate box
    if len(box) != 4:
        return EditResult(
            success=False,
            operation=EditOperation.CROP,
            parameters={"box": box},
            error="Box must have 4 elements: (left, upper, right, lower)",
        )

    left, upper, right, lower = box
    if left >= right or upper >= lower:
        return EditResult(
            success=False,
            operation=EditOperation.CROP,
            parameters={"box": box},
            error="Invalid crop box: left >= right or upper >= lower",
        )

    input_hash = sha256_file(input_path)

    try:
        with Image.open(input_path) as img:
            # Validate box is within image bounds
            img_width, img_height = img.size
            if left < 0 or upper < 0 or right > img_width or lower > img_height:
                return EditResult(
                    success=False,
                    operation=EditOperation.CROP,
                    parameters={"box": box},
                    error=f"Crop box {box} exceeds image bounds ({img_width}, {img_height})",
                )

            # Check for zero area
            if (right - left) * (lower - upper) == 0:
                return EditResult(
                    success=False,
                    operation=EditOperation.CROP,
                    parameters={"box": box},
                    error="Crop box has zero area",
                )

            img = img.crop(box)

            _save_png_atomic(img, output_path)

    except Exception as e:
        return EditResult(
            success=False,
            operation=EditOperation.CROP,
            parameters={"box": box},
            input_sha256=input_hash,
            error=str(e),
        )

    output_hash = sha256_file(output_path)
    with Image.open(output_path) as img:
        output_size = img.size

    elapsed = (time.time() - start_time) * 1000

    return EditResult(
        success=True,
        operation=EditOperation.CROP,
        parameters={"box": box},
        input_sha256=input_hash,
        output_sha256=output_hash,
        output_size=output_size,
        execution_time_ms=elapsed,
    )


def local_adjustment_l3(
    input_path: Path,
    output_path: Path,
    *,
    box: tuple[int, int, int, int],
    exposure: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    feather: int = 0,
) -> EditResult:
    """Apply a bounded local adjustment while preserving the parent image."""
    start_time = time.time()
    parameters = {
        "box": box,
        "exposure": exposure,
        "contrast": contrast,
        "saturation": saturation,
        "feather": feather,
    }
    error = _validate_input_output(input_path, output_path)
    if error:
        return EditResult(
            success=False,
            operation=EditOperation.LOCAL_ADJUSTMENT,
            parameters=parameters,
            error=error,
        )
    if len(box) != 4:
        return EditResult(
            success=False,
            operation=EditOperation.LOCAL_ADJUSTMENT,
            parameters=parameters,
            error="Box must have 4 elements: (left, upper, right, lower)",
        )
    for value, validator in (
        (exposure, _validate_exposure),
        (contrast, _validate_contrast),
        (saturation, _validate_saturation),
    ):
        error = validator(value)
        if error:
            return EditResult(
                success=False,
                operation=EditOperation.LOCAL_ADJUSTMENT,
                parameters=parameters,
                error=error,
            )
    if not isinstance(feather, int) or not 0 <= feather <= 256:
        return EditResult(
            success=False,
            operation=EditOperation.LOCAL_ADJUSTMENT,
            parameters=parameters,
            error="Feather must be an integer between 0 and 256",
        )

    left, upper, right, lower = box
    if left >= right or upper >= lower:
        return EditResult(
            success=False,
            operation=EditOperation.LOCAL_ADJUSTMENT,
            parameters=parameters,
            error="Invalid local adjustment box",
        )

    input_hash = sha256_file(input_path)
    try:
        with Image.open(input_path) as source:
            source = source.convert("RGB")
            width, height = source.size
            if left < 0 or upper < 0 or right > width or lower > height:
                return EditResult(
                    success=False,
                    operation=EditOperation.LOCAL_ADJUSTMENT,
                    parameters=parameters,
                    input_sha256=input_hash,
                    error=f"Local adjustment box {box} exceeds image bounds ({width}, {height})",
                )

            adjusted = source.copy()
            if exposure != 0.0:
                adjusted = ImageEnhance.Brightness(adjusted).enhance(1.0 + exposure)
            if contrast != 1.0:
                adjusted = ImageEnhance.Contrast(adjusted).enhance(contrast)
            if saturation != 1.0:
                adjusted = ImageEnhance.Color(adjusted).enhance(saturation)

            mask = Image.new("L", source.size, 0)
            ImageDraw.Draw(mask).rectangle((left, upper, right - 1, lower - 1), fill=255)
            if feather:
                mask = mask.filter(ImageFilter.GaussianBlur(feather))
            output = Image.composite(adjusted, source, mask)
            _save_png_atomic(output, output_path)
    except Exception as exc:
        return EditResult(
            success=False,
            operation=EditOperation.LOCAL_ADJUSTMENT,
            parameters=parameters,
            input_sha256=input_hash,
            error=str(exc),
        )

    output_hash = sha256_file(output_path)
    with Image.open(output_path) as image:
        output_size = image.size
    return EditResult(
        success=True,
        operation=EditOperation.LOCAL_ADJUSTMENT,
        parameters=parameters,
        input_sha256=input_hash,
        output_sha256=output_hash,
        output_size=output_size,
        execution_time_ms=(time.time() - start_time) * 1000,
    )


def resize_for_media(
    input_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    fit: str = "contain",
) -> EditResult:
    """Resize image for specific media dimensions.

    Args:
        input_path: Path to input image.
        output_path: Path to output image.
        width: Target width.
        height: Target height.
        fit: Resize mode - "contain" (preserve aspect, fit within) or "cover" (fill, may crop).

    Returns:
        EditResult with operation details.
    """
    start_time = time.time()

    # Validate paths
    error = _validate_input_output(input_path, output_path)
    if error:
        return EditResult(
            success=False,
            operation=EditOperation.RESIZE,
            parameters={"width": width, "height": height, "fit": fit},
            error=error,
        )

    # Validate dimensions
    if width <= 0 or height <= 0:
        return EditResult(
            success=False,
            operation=EditOperation.RESIZE,
            parameters={"width": width, "height": height, "fit": fit},
            error="Width and height must be positive",
        )

    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        return EditResult(
            success=False,
            operation=EditOperation.RESIZE,
            parameters={"width": width, "height": height, "fit": fit},
            error=f"Dimensions must not exceed {MAX_DIMENSION}",
        )

    if fit not in ("contain", "cover"):
        return EditResult(
            success=False,
            operation=EditOperation.RESIZE,
            parameters={"width": width, "height": height, "fit": fit},
            error="Fit must be 'contain' or 'cover'",
        )

    input_hash = sha256_file(input_path)

    try:
        with Image.open(input_path) as img:
            img_width, img_height = img.size

            if fit == "contain":
                # Preserve aspect ratio, fit within dimensions
                ratio = min(width / img_width, height / img_height)
                new_width = int(img_width * ratio)
                new_height = int(img_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            else:
                # Cover: fill dimensions, may crop
                ratio = max(width / img_width, height / img_height)
                new_width = int(img_width * ratio)
                new_height = int(img_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Center crop to target dimensions
                left = (new_width - width) // 2
                upper = (new_height - height) // 2
                img = img.crop((left, upper, left + width, upper + height))

            _save_png_atomic(img, output_path)

    except Exception as e:
        return EditResult(
            success=False,
            operation=EditOperation.RESIZE,
            parameters={"width": width, "height": height, "fit": fit},
            input_sha256=input_hash,
            error=str(e),
        )

    output_hash = sha256_file(output_path)
    with Image.open(output_path) as img:
        output_size = img.size

    elapsed = (time.time() - start_time) * 1000

    return EditResult(
        success=True,
        operation=EditOperation.RESIZE,
        parameters={"width": width, "height": height, "fit": fit},
        input_sha256=input_hash,
        output_sha256=output_hash,
        output_size=output_size,
        execution_time_ms=elapsed,
    )
