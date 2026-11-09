"""Kiểm tra âm tiết tiếng Việt để phát hiện OCR đặt sai dấu (vd. "vién" thay vì "viên").

Tesseract trên bản scan mờ ít khi bỏ hẳn dấu mà hay đặt sai dấu, và độ tin cậy vẫn cao.
Chỉ xét từ có dấu: từ không dấu có thể là tiếng Anh, tên riêng, nên không kết luận được.
"""

import re
import unicodedata

ONSETS = sorted(
    "b c ch d đ g gh gi h k kh l m n ng ngh nh p ph qu r s t th tr v x".split(),
    key=len,
    reverse=True,
)
RHYMES = set(
    """a ai ao au ay am an ang anh ap at ac ach ăm ăn ăng ăp ăt ăc âu ây âm ân âng âp ât âc
    e eo em en eng ep et ec ê êu êm ên ênh êp êt êch i ia iu im in inh ip it ich iêu iêm iên
    iêng iêp iêt iêc o oi om on ong op ot oc oa oai oao oay oam oan oang oanh oap oat oac oach
    oăm oăn oăng oăt oăc oe oeo oen oet ooc oong ô ôi ôm ôn ông ôp ôt ôc ơ ơi ơm ơn ơp ơt u ua
    ui um un ung up ut uc uân uâng uât uây uê uêch uênh uơ uy uya uyu uyên uyêt uych uynh uyt
    uôi uôm uôn uông uôt uôc ư ưa ưi ưu ưng ưt ưc ưm ươi ươu ươm ươn ương ươp ươt ươc y yêu
    yên yêm yêt""".split()
)
# dấu thanh (huyền, sắc, hỏi, ngã, nặng); dấu mũ, móc, trăng thì giữ
TONES = {"̀", "́", "̉", "̃", "̣"}
VN_CHARS = set("ăâđêôơư")
WORD = re.compile(r"[^\W\d_]+")


def strip_tone(word: str) -> tuple[str, int]:
    """(từ bỏ dấu thanh, số dấu thanh)."""
    nfd = unicodedata.normalize("NFD", word.lower())
    tones = sum(c in TONES for c in nfd)
    base = "".join(c for c in nfd if c not in TONES)
    return unicodedata.normalize("NFC", base), tones


def has_diacritic(word: str) -> bool:
    base, tones = strip_tone(word)
    return tones > 0 or any(c in VN_CHARS for c in base)


def is_valid(word: str) -> bool:
    base, tones = strip_tone(word)
    if tones > 1 or not base:
        return False
    onset = next((o for o in ONSETS if base.startswith(o) and len(base) > len(o)), "")
    rhyme = base[len(onset) :]
    if onset == "gi" and rhyme == "":  # "gì"
        return True
    return rhyme in RHYMES or (onset == "gi" and ("i" + rhyme) in RHYMES)  # "gìn" = gi + in


def _is_abbrev(word: str) -> bool:
    """QĐ, HĐQT, TNHH: viết hoa, không có dấu thanh. "THUÉ" có dấu thanh nên vẫn bị xét."""
    return word.isupper() and len(word) <= 6 and strip_tone(word)[1] == 0


def bad_diacritic_ratio(text: str) -> tuple[float, int]:
    """(tỷ lệ từ có dấu nhưng không phải âm tiết hợp lệ, số từ có dấu)."""
    words = [w for w in WORD.findall(text) if has_diacritic(w) and not _is_abbrev(w)]
    if not words:
        return 0.0, 0
    return sum(not is_valid(w) for w in words) / len(words), len(words)
