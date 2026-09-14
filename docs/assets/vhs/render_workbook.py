#!/usr/bin/env python3
"""Render a sheet of an .xlsx workbook to a cropped PNG with headless LibreOffice.

    docs/assets/vhs/render_workbook.py /tmp/vitreus-demo/sales-reviewed.xlsx Sales \
        docs/assets/showcase/workbook.png --hide D E F G H I K L

Used for the README showcase: apply a manifest with `vitreus analyze ... -o out.xlsx`, then render the
result. Only the workbook is drawn, so the image never contains anything from the desktop.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import openpyxl
from PIL import Image, ImageChops


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("sheet")
    parser.add_argument("output", type=Path)
    parser.add_argument("--hide", nargs="*", default=[], help="Column letters to hide in the render")
    parser.add_argument("--margin", type=int, default=20)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.workbook)
    for name in list(wb.sheetnames):
        if name != args.sheet:
            del wb[name]
    ws = wb[args.sheet]
    for col in args.hide:
        ws.column_dimensions[col.upper()].hidden = True
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.gridLines = True
    ws.page_margins.left = ws.page_margins.right = ws.page_margins.top = ws.page_margins.bottom = 0.2

    with tempfile.TemporaryDirectory(prefix="vitreus-render-") as tmp:
        staged = Path(tmp) / "render.xlsx"
        wb.save(staged)
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "png", "--outdir", tmp, str(staged)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        image = Image.open(Path(tmp) / "render.png").convert("RGB")
        background = Image.new("RGB", image.size, (255, 255, 255))
        box = ImageChops.difference(image, background).getbbox()
        if box is None:
            print("rendered page is blank", file=sys.stderr)
            return 1
        m = args.margin
        cropped = image.crop((max(box[0] - m, 0), max(box[1] - m, 0), min(box[2] + m, image.width), min(box[3] + m, image.height)))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(args.output)
    print(f"{args.output} {cropped.size[0]}x{cropped.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
