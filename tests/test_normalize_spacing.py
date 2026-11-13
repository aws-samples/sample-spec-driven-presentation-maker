"""normalize_spacing: a half-width space between CJK letters and ASCII, none next to
Japanese punctuation."""
import pytest

from sdpm.utils.text import is_cjk_punctuation, normalize_spacing


@pytest.mark.parametrize("src, expected", [
    ("AWSのLambda", "AWS の Lambda"),
    ("ログ3TB", "ログ 3TB"),
    ("サーバーA", "サーバー A"),
    ("「Lambda」で", "「Lambda」で"),
    ("月額(概算)は", "月額 (概算) は"),
])
def test_space_between_cjk_letters_and_ascii(src, expected):
    assert normalize_spacing(src) == expected


@pytest.mark.parametrize("src, expected", [
    ("DBは、DBを。2026年", "DB は、DB を。2026 年"),
    ("DB、S3", "DB、S3"),
    ("A・B", "A・B"),
    ("AWS／Azure", "AWS／Azure"),
    ("1〜5台", "1〜5 台"),
    ("合計：100件", "合計：100 件"),
    ("Step1：準備", "Step1：準備"),
    ("（AWS）", "（AWS）"),
    ("100％", "100％"),
])
def test_no_space_next_to_japanese_punctuation(src, expected):
    assert normalize_spacing(src) == expected


def test_letter_like_marks_are_not_punctuation():
    for ch in "々〆〇ー":
        assert not is_cjk_punctuation(ch)
    for ch in "、。・「」（）／：〜　":
        assert is_cjk_punctuation(ch)
