"""EE542 Lab 9 Part 4: the F-1 knowledge base's manifest helpers."""
import json
import re
from pathlib import Path

COLLECTION = "f1"
DATA = Path(__file__).resolve().parent.parent.parent.parent / "data" / "f1"
RAW = DATA / "raw"


def load_manifest() -> list[dict]:
    return json.loads((DATA / "manifest.json").read_text())


def display_name(m: dict) -> str:
    ext = m["file"].rsplit(".", 1)[1]
    title = re.sub(r"[/\\\\]", "-", m["title"])
    return f"{m['agency']}: {title}.{ext}"


def url_for() -> dict[str, dict]:
    """display name (as stored in rag_documents.filename) -> manifest entry."""
    return {display_name(m): m for m in load_manifest()}
