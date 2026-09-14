from interfaces.ui import compress_highlights


def test_compress_highlights_merges_contiguous_cells_in_a_row():
    cells = [(f"Sheet1!{c}3", "#ef4444") for c in "ABCDEFGHIJK"] + [("Sheet1!A9", "#ef4444"), ("Sheet1!B9", "#ef4444")]

    assert compress_highlights(cells) == [("Sheet1!A3:K3", "#ef4444"), ("Sheet1!A9:B9", "#ef4444")]


def test_compress_highlights_keeps_gaps_colours_and_sheets_apart():
    cells = [("S!A1", "#f00"), ("S!B1", "#0f0"), ("S!D1", "#f00"), ("Other!A1", "#f00"), ("S!A2", "#f00")]

    assert compress_highlights(cells) == [("S!A1", "#f00"), ("S!B1", "#0f0"), ("S!D1", "#f00"), ("Other!A1", "#f00"), ("S!A2", "#f00")]
