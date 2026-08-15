"""Compare original and candidate images for visual-art-direction skill.

Engineering comparison only - does NOT output aesthetic judgments like
"更美", "更高级", "通过摄影师审核", etc.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from .contracts import AdapterHealth, Capability, ComparisonResult
from .evidence import sha256_file


class LocalCompareAdapter:
    """Explicit adapter declaration for local engineering comparison."""

    name = "local-compare"
    version = "1.0.0"

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities={Capability.V3_RESULT_COMPARISON},
            evidence="Pillow local comparison reports are available",
        )

    def capabilities(self) -> set[Capability]:
        return {Capability.V3_RESULT_COMPARISON}

    def compare(self, original: Path, candidate: Path, report_dir: Path) -> ComparisonResult:
        return compare_images(original, candidate, report_dir)


def _get_image_info(path: Path) -> tuple[bool, tuple[int, int], str]:
    """Get image readability, size, and hash.

    Returns:
        Tuple of (readable, size, sha256).
    """
    if not path.exists() or not path.is_file():
        return False, (0, 0), ""

    try:
        with Image.open(path) as img:
            img.verify()

        # Re-open after verify
        with Image.open(path) as img:
            size = img.size

        hash_val = sha256_file(path)
        return True, size, hash_val

    except Exception:
        return False, (0, 0), ""


def _compute_pixel_diff(
    original: Path, candidate: Path
) -> tuple[int, int, tuple[int, int, int, int] | None]:
    """Compute pixel-level differences.

    Returns:
        Tuple of (changed_pixels, total_pixels, bounding_box).
    """
    try:
        with Image.open(original) as orig_img:
            orig_img = orig_img.convert("RGB")
            orig_data = list(orig_img.get_flattened_data())
            orig_size = orig_img.size

        with Image.open(candidate) as cand_img:
            cand_img = cand_img.convert("RGB")
            cand_data = list(cand_img.get_flattened_data())
            cand_size = cand_img.size

        # Sizes must match for pixel comparison
        if orig_size != cand_size:
            return -1, -1, None

        total_pixels = len(orig_data)
        changed_pixels = 0
        min_x, min_y = orig_size[0], orig_size[1]
        max_x, max_y = 0, 0

        for i, (o, c) in enumerate(zip(orig_data, cand_data, strict=False)):
            if o != c:
                changed_pixels += 1
                x = i % orig_size[0]
                y = i // orig_size[0]
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

        if changed_pixels == 0:
            return 0, total_pixels, None

        bbox = (min_x, min_y, max_x + 1, max_y + 1)
        return changed_pixels, total_pixels, bbox

    except Exception:
        return -1, -1, None


def _generate_html_report(
    original: Path,
    candidate: Path,
    result: ComparisonResult,
    report_path: Path,
) -> None:
    """Generate HTML comparison report."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Image Comparison Report</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; }}
        .container {{ display: flex; gap: 20px; }}
        .image-box {{ border: 1px solid #ccc; padding: 10px; }}
        img {{ max-width: 400px; max-height: 300px; }}
        table {{ border-collapse: collapse; margin: 20px 0; }}
        td, th {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
        th {{ background: #f0f0f0; }}
        .warning {{ color: orange; }}
        .error {{ color: red; }}
    </style>
</head>
<body>
    <h1>Image Comparison Report</h1>
    <p><strong>Note:</strong> This is an engineering comparison only.
    It does NOT indicate aesthetic quality or whether changes are improvements.</p>

    <h2>Images</h2>
    <div class="container">
        <div class="image-box">
            <h3>Original</h3>
            <img src="{original.as_uri()}" alt="Original">
            <p>Size: {result.original_size[0]} x {result.original_size[1]}</p>
            <p>SHA-256: {result.original_sha256[:16]}...</p>
        </div>
        <div class="image-box">
            <h3>Candidate</h3>
            <img src="{candidate.as_uri()}" alt="Candidate">
            <p>Size: {result.candidate_size[0]} x {result.candidate_size[1]}</p>
            <p>SHA-256: {result.candidate_sha256[:16]}...</p>
        </div>
    </div>

    <h2>Engineering Metrics</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Original Readable</td><td>{"Yes" if result.original_readable else "No"}</td></tr>
        <tr><td>Candidate Readable</td><td>{"Yes" if result.candidate_readable else "No"}</td></tr>
        <tr><td>Pixel Change Summary</td><td>{result.pixel_change_summary}</td></tr>
        <tr><td>Change Bounding Box</td><td>{result.change_bounding_box}</td></tr>
    </table>

    <h2>Limitations</h2>
    <ul>
        <li>Pixel changes do not indicate whether the main problem was improved.</li>
        <li>Engineering metrics do not replace aesthetic judgment.</li>
        <li>User confirmation is still required.</li>
    </ul>

    <p><em>Generated: {datetime.now().isoformat()}</em></p>
</body>
</html>"""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)


def compare_images(
    original: Path,
    candidate: Path,
    report_dir: Path,
) -> ComparisonResult:
    """Compare original and candidate images.

    Args:
        original: Path to original image.
        candidate: Path to candidate image.
        report_dir: Directory for reports.

    Returns:
        ComparisonResult with engineering comparison.
    """
    result = ComparisonResult()

    # Get original info
    orig_readable, orig_size, orig_hash = _get_image_info(original)
    result.original_readable = orig_readable
    result.original_size = orig_size
    result.original_sha256 = orig_hash

    if not orig_readable:
        result.error = f"Original image not readable: {original}"
        return result

    # Get candidate info
    cand_readable, cand_size, cand_hash = _get_image_info(candidate)
    result.candidate_readable = cand_readable
    result.candidate_size = cand_size
    result.candidate_sha256 = cand_hash

    if not cand_readable:
        result.error = f"Candidate image not readable: {candidate}"
        return result

    # Compute pixel differences
    if orig_size == cand_size:
        changed, total, bbox = _compute_pixel_diff(original, candidate)
        if changed >= 0:
            pct = (changed / total * 100) if total > 0 else 0
            result.pixel_change_summary = f"{changed}/{total} pixels changed ({pct:.1f}%)"
            result.change_bounding_box = bbox
        else:
            result.pixel_change_summary = "Could not compute pixel differences"
    else:
        result.pixel_change_summary = f"Size mismatch: {orig_size} vs {cand_size}"

    # Generate JSON report
    report_json_path = report_dir / "comparison-report.json"
    report_json_path.parent.mkdir(parents=True, exist_ok=True)

    report_data = {
        "original": str(original),
        "candidate": str(candidate),
        "original_readable": result.original_readable,
        "candidate_readable": result.candidate_readable,
        "original_sha256": result.original_sha256,
        "candidate_sha256": result.candidate_sha256,
        "original_size": list(result.original_size),
        "candidate_size": list(result.candidate_size),
        "pixel_change_summary": result.pixel_change_summary,
        "change_bounding_box": (
            list(result.change_bounding_box) if result.change_bounding_box else None
        ),
        "generated_at": datetime.now().isoformat(),
        "limitations": [
            "Pixel changes do not indicate whether the main problem was improved",
            "Engineering metrics do not replace aesthetic judgment",
            "User confirmation is still required",
        ],
    }

    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    result.report_json_path = report_json_path

    # Generate HTML report
    report_html_path = report_dir / "comparison-report.html"
    _generate_html_report(original, candidate, result, report_html_path)
    result.report_html_path = report_html_path

    return result
