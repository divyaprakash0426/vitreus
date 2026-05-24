from pathlib import Path

from PIL import Image

from core.vision import VisionInput


def test_vision_input_reports_image_metadata_and_prompt(tmp_path: Path):
    image_path = tmp_path / "receipt.png"
    Image.new("RGB", (32, 16), color=(255, 255, 255)).save(image_path)

    payload = VisionInput.from_file(image_path, purpose="receipt").to_prompt_payload()

    assert payload == {
        "path": str(image_path),
        "purpose": "receipt",
        "format": "PNG",
        "width": 32,
        "height": 16,
        "mode": "RGB",
        "instruction": "Extract merchant, date, line items, totals, and tax fields as spreadsheet-ready JSON.",
    }
