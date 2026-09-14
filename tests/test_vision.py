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


def test_encode_image_downsizes_large_images_and_reports_mime(tmp_path: Path):
    from core.vision import encode_image

    big = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), color=(10, 20, 30)).save(big)

    data, mime = encode_image(big, max_side=1600)

    assert mime in {"image/jpeg", "image/png"}
    with Image.open(__import__("io").BytesIO(data)) as reloaded:
        assert max(reloaded.size) <= 1600
        assert reloaded.size[0] / reloaded.size[1] == 4.0


def test_encode_image_keeps_small_png_as_png(tmp_path: Path):
    from core.vision import encode_image

    small = tmp_path / "small.png"
    Image.new("RGBA", (40, 30), color=(0, 0, 0, 0)).save(small)

    data, mime = encode_image(small)

    assert mime == "image/png" and data[:4] == b"\x89PNG"


def test_extraction_prompt_mentions_rows_schema_for_each_purpose():
    from core.vision import extraction_prompt

    for purpose in ("receipt", "chart", "table"):
        prompt = extraction_prompt(purpose)
        assert '"rows"' in prompt and '"sheet_name"' in prompt and purpose in prompt.lower()


def test_extract_table_sends_one_image_and_parses_rows(tmp_path: Path):
    from core.vision import extract_table

    image_path = tmp_path / "receipt.png"
    Image.new("RGB", (64, 64), color=(255, 255, 255)).save(image_path)

    class Scripted:
        name = "scripted"
        model = "m"

        def __init__(self):
            self.calls = []

        def chat(self, messages, images=None):
            self.calls.append((messages, images))
            return 'Here you go:\n```json\n{"sheet_name": "Receipt", "summary": "Coffee shop receipt", "rows": [["Item", "Price"], ["Latte", 4.5]]}\n```'

        def list_models(self):
            return []

    backend = Scripted()
    result = extract_table(backend, image_path, purpose="receipt")

    assert result == {"sheet_name": "Receipt", "summary": "Coffee shop receipt", "rows": [["Item", "Price"], ["Latte", 4.5]]}
    messages, images = backend.calls[0]
    assert len(images) == 1 and images[0][:4] == b"\x89PNG"
    assert messages[-1]["role"] == "user" and "receipt" in messages[-1]["content"].lower()


def test_extract_table_rejects_reply_without_rows(tmp_path: Path):
    import pytest

    from core.vision import VisionError, extract_table

    image_path = tmp_path / "chart.png"
    Image.new("RGB", (8, 8)).save(image_path)

    class Bad:
        name = "bad"
        model = "m"

        def chat(self, messages, images=None):
            return '{"summary": "no table here"}'

        def list_models(self):
            return []

    with pytest.raises(VisionError, match="rows"):
        extract_table(Bad(), image_path, purpose="chart")


def test_extract_table_normalises_ragged_rows_and_dict_rows(tmp_path: Path):
    from core.vision import extract_table

    image_path = tmp_path / "t.png"
    Image.new("RGB", (8, 8)).save(image_path)

    class Dicts:
        name = "d"
        model = "m"

        def chat(self, messages, images=None):
            return '{"sheet_name": "T", "rows": [{"Item": "A", "Qty": 1}, {"Item": "B"}]}'

        def list_models(self):
            return []

    result = extract_table(Dicts(), image_path, purpose="table")

    assert result["rows"] == [["Item", "Qty"], ["A", 1], ["B", None]]
