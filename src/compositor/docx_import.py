from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}


def extract_docx_paragraphs(path: Path) -> list[str]:
    """Extract plain paragraphs from a .docx file using stdlib only."""
    with zipfile.ZipFile(path) as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    text_tag = f"{{{WORD_NS}}}t"
    break_tag = f"{{{WORD_NS}}}br"
    tab_tag = f"{{{WORD_NS}}}tab"

    for para in root.findall(".//w:body/w:p", NS):
        parts: list[str] = []
        for node in para.iter():
            if node.tag == text_tag:
                parts.append(node.text or "")
            elif node.tag == break_tag:
                parts.append("\n")
            elif node.tag == tab_tag:
                parts.append("\t")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs
