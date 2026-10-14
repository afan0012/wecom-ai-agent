from app.wecom_kf import _split_wechat_text


def test_text_is_split_on_utf8_boundaries_and_capped_at_five_messages() -> None:
    pieces = _split_wechat_text("你" * 5000)
    assert len(pieces) == 5
    assert all(len(piece.encode("utf-8")) <= 2048 for piece in pieces)
    assert "发送上限" in pieces[-1]
