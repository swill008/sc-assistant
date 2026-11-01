"""Personal notes, stored as plain text beside the other user data.

Nothing clever on purpose: one UTF-8 file the player can open, back up or edit
in any editor.  Reads and writes go through :mod:`app.safe_store`: a file that
could not be read is never saved over, the previous file is kept as
``notes.txt.bak``, and a file saved in another encoding still opens.
"""
from __future__ import annotations

from pathlib import Path

from .config import config_dir
from .safe_store import LOAD_FAILED, StoreNotLoaded, load_text, write_text

FILE_NAME = "notes.txt"


class NotesStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else config_dir() / FILE_NAME
        self.load_failed = False
        self.error = ""
        self.encoding = ""

    def load(self) -> str:
        """Return the notes; on a failed read return "" and set load_failed."""
        loaded = load_text(self.path, default="")
        if loaded.value is LOAD_FAILED:
            self.load_failed = True
            self.error = loaded.error
            return ""
        self.load_failed = False
        self.error = ""
        self.encoding = loaded.encoding
        return loaded.value

    def save(self, text: str) -> None:
        """Write *text*; raises OSError (StoreNotLoaded after a failed read)."""
        if self.load_failed:
            raise StoreNotLoaded(f"Not saved: {self.error}")
        write_text(self.path, text)
        self.encoding = "utf-8"
