"""リーダーのユニットテスト。"""

import os
import tempfile

import pytest


class TestReaderDispatch:
    """リーダー選択ロジックのテスト。"""

    def test_pdf_reader(self):
        from readers import get_reader
        reader = get_reader("test.pdf")
        assert reader.__name__.endswith("pdf")

    def test_markdown_reader(self):
        from readers import get_reader
        reader = get_reader("test.md")
        assert reader.__name__.endswith("markdown")

    def test_rst_reader(self):
        from readers import get_reader
        reader = get_reader("test.rst")
        assert reader.__name__.endswith("rst")

    def test_html_reader(self):
        from readers import get_reader
        reader = get_reader("test.html")
        assert reader.__name__.endswith("html")

    def test_docx_reader(self):
        from readers import get_reader
        reader = get_reader("test.docx")
        assert reader.__name__.endswith("docx")

    def test_csv_reader(self):
        from readers import get_reader
        reader = get_reader("test.csv")
        assert reader.__name__.endswith("csv")

    def test_code_reader_fallback(self):
        from readers import get_reader
        reader = get_reader("test.go")
        assert reader.__name__.endswith("code")


class TestMarkdownReader:
    def test_read(self):
        from readers.markdown import read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Hello\n\nWorld\n")
            f.flush()
            result = read(f.name)
        os.unlink(f.name)
        assert "Hello" in result
        assert "World" in result


@pytest.mark.skipif(
    not pytest.importorskip("bs4", reason="beautifulsoup4 not installed"),
    reason="beautifulsoup4 not installed",
)
class TestHtmlReader:
    def test_read(self):
        from readers.html import read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body><h1>Title</h1><p>Content</p></body></html>")
            f.flush()
            result = read(f.name)
        os.unlink(f.name)
        assert "Title" in result
        assert "Content" in result

    def test_html_to_markdown(self):
        from readers.html import _html_to_markdown
        result = _html_to_markdown("<h1>Hello</h1><p>World</p>")
        assert "Hello" in result
        assert "World" in result


class TestRstReader:
    def test_read(self):
        try:
            import docutils  # noqa: F401
        except ImportError:
            pytest.skip("docutils not installed")
        from readers.rst import read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rst", delete=False) as f:
            f.write("Title\n=====\n\nSome paragraph.\n\n- Item 1\n- Item 2\n")
            f.flush()
            result = read(f.name)
        os.unlink(f.name)
        assert "Title" in result
        assert "Some paragraph" in result


@pytest.mark.skipif(
    not pytest.importorskip("pandas", reason="pandas not installed"),
    reason="pandas not installed",
)
class TestCsvReader:
    def test_read_csv(self):
        from readers.csv import read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,value\nfoo,1\nbar,2\n")
            f.flush()
            result = read(f.name)
        os.unlink(f.name)
        assert "name" in result
        assert "foo" in result


class TestCodeReader:
    def test_read(self):
        from readers.code import read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# comment\ndef hello():\n    pass\n")
            f.flush()
            result = read(f.name)
        os.unlink(f.name)
        assert "hello" in result
