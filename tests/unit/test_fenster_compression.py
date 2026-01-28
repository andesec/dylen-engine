import uuid

from app.schema.fenster import FensterWidget
from app.utils.compression import compress_html, decompress_html


def test_compression_roundtrip_simple():
  original = "<html><body>Hello</body></html>"
  compressed = compress_html(original)
  decompressed = decompress_html(compressed)
  assert original == decompressed


def test_compression_roundtrip_large():
  # 100KB html string
  original = "<div>Content</div>" * 10000
  assert len(original) > 100000
  compressed = compress_html(original)
  decompressed = decompress_html(compressed)
  assert original == decompressed


def test_fenster_widget_model():
  fenster_id = uuid.uuid4()
  content = compress_html("test")
  widget = FensterWidget(fenster_id=fenster_id, type="inline_blob", content=content, url=None)
  assert widget.fenster_id == fenster_id
  assert widget.type == "inline_blob"
  assert widget.content == content
  assert widget.url is None
