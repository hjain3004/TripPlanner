#!/usr/bin/env python3
"""Stage 1 of the plate pipeline: photo -> flat posterized PNG in the token palette.

The trace engine preserves whatever colour and detail it is given, so both
abstraction and palette unity have to be established *before* vectorizing.
This stage does that by mapping image luminance onto a fixed ramp derived from
the OKLCH tokens in frontend/src/themes/singapore.css. Two plates from two
unrelated photographs come out in the same five colours by construction.

    python3 posterize.py in.jpg out.png [--levels 5] [--smooth 9] [--width 1100]

--smooth is the abstraction dial: larger median windows collapse detail into
flat regions. --levels is the second dial: fewer bands reads more graphic.
"""

from __future__ import annotations

import argparse
import math

import numpy as np
from PIL import Image, ImageFilter

# --- token ramp ----------------------------------------------------------------
# Lifted from singapore.css. MID is the one derived value: singapore.css jumps
# straight from celadon-1 (L 0.848) to mangrove (L 0.320), which posterizes into
# a hard pale-to-black step with no modelling. MID interpolates that gap in the
# same hue family rather than introducing a new one.
RAMP_OKLCH = [
    (0.979, 0.008, 91),   # --th-surface     paper
    (0.917, 0.016, 161),  # --th-accent-2    celadon-2
    (0.848, 0.027, 167),  # --th-accent-1    celadon-1
    (0.560, 0.045, 174),  # derived          mid
    (0.320, 0.042, 181),  # --th-primary     mangrove
]


def oklch_to_srgb(lightness: float, chroma: float, hue_deg: float) -> tuple[int, int, int]:
    """OKLCh -> 8-bit sRGB, via OKLab and linear sRGB."""
    hue = math.radians(hue_deg)
    a = chroma * math.cos(hue)
    b = chroma * math.sin(hue)

    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3

    linear = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    out = []
    for channel in linear:
        channel = max(0.0, min(1.0, channel))
        encoded = 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
        out.append(int(round(max(0.0, min(1.0, encoded)) * 255)))
    return tuple(out)  # type: ignore[return-value]


def build_ramp(levels: int) -> list[tuple[int, int, int]]:
    """Take `levels` evenly spaced stops from the token ramp, always keeping both ends."""
    if levels >= len(RAMP_OKLCH):
        chosen = RAMP_OKLCH
    else:
        idx = [round(i * (len(RAMP_OKLCH) - 1) / (levels - 1)) for i in range(levels)]
        chosen = [RAMP_OKLCH[i] for i in idx]
    return [oklch_to_srgb(*stop) for stop in chosen]


def posterize(path_in: str, path_out: str, levels: int, smooth: int, width: int) -> None:
    img = Image.open(path_in).convert("RGB")

    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)

    # Median first: it flattens texture while holding edges, which is what keeps
    # the silhouette readable after quantizing. Gaussian afterwards softens the
    # stair-stepping the median leaves behind, so traced edges come out smooth
    # rather than serrated — that serration was the "crude" quality earlier.
    if smooth > 1:
        img = img.filter(ImageFilter.MedianFilter(size=smooth if smooth % 2 else smooth + 1))
        img = img.filter(ImageFilter.GaussianBlur(radius=smooth / 6))

    arr = np.asarray(img, dtype=np.float32)
    luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]

    # Quantile thresholds rather than fixed ones: a source shot against bright sky
    # and one shot at dusk both then use the full ramp instead of collapsing into
    # two bands. Keeps plates consistent across wildly different photographs.
    cuts = np.quantile(luma, [i / levels for i in range(1, levels)])
    band = np.digitize(luma, cuts)

    ramp = build_ramp(levels)
    # Ramp runs light -> dark; band 0 is the darkest luminance, so invert.
    lut = np.array(ramp[::-1], dtype=np.uint8)
    Image.fromarray(lut[band]).save(path_out)

    print(f"{path_out}  {img.width}x{img.height}  levels={levels} smooth={smooth}")
    for i, rgb in enumerate(ramp):
        print(f"  ramp[{i}] #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--levels", type=int, default=5, help="palette steps (fewer = more graphic)")
    ap.add_argument("--smooth", type=int, default=9, help="median window (larger = more abstract)")
    ap.add_argument("--width", type=int, default=1100, help="working width in px")
    args = ap.parse_args()
    posterize(args.src, args.dst, args.levels, args.smooth, args.width)


if __name__ == "__main__":
    main()
