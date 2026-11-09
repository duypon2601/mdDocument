"""HTML -> Markdown (bỏ script/style/nav)."""

from bs4 import BeautifulSoup
from markdownify import markdownify


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def html_to_markdown(data: bytes) -> str:
    soup = BeautifulSoup(decode_text(data), "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    body = soup.body or soup
    return markdownify(str(body), heading_style="ATX").strip()
