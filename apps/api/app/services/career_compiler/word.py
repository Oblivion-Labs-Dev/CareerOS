"""DOCX -> PDF conversion by the layout authority: Microsoft Word (COM) on Windows, else LibreOffice.

Word runs on one dedicated thread that owns the COM apartment, so request threads never touch COM.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path

WD_EXPORT_PDF = 17
WD_STATISTIC_PAGES = 2


class ConverterUnavailable(RuntimeError):
    pass


class Converter:
    name = "none"

    def to_pdf(self, docx: bytes) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError


class WordConverter(Converter):
    name = "Microsoft Word"

    def __init__(self) -> None:
        self._jobs: queue.Queue[tuple[bytes, Future]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="careeros-word", daemon=True)
        self._thread.start()

    def to_pdf(self, docx: bytes) -> bytes:
        future: Future = Future()
        self._jobs.put((docx, future))
        return future.result(timeout=120)

    def _run(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        word = None
        workdir = Path(tempfile.mkdtemp(prefix="careeros-word-"))
        while True:
            docx, future = self._jobs.get()
            source, target = workdir / "resume.docx", workdir / "resume.pdf"
            try:
                if word is None:
                    word = win32com.client.DispatchEx("Word.Application")
                    word.Visible = False
                    word.DisplayAlerts = 0
                source.write_bytes(docx)
                target.unlink(missing_ok=True)
                doc = word.Documents.Open(str(source), False, True, False)
                try:
                    doc.ExportAsFixedFormat(str(target), WD_EXPORT_PDF)
                finally:
                    doc.Close(0)
                future.set_result(target.read_bytes())
            except Exception as exc:  # noqa: BLE001 - a dead Word instance is restarted on the next job
                try:
                    if word is not None:
                        word.Quit(0)
                except Exception:  # noqa: BLE001
                    pass
                word = None
                future.set_exception(ConverterUnavailable(f"Word could not convert the resume: {exc}"))


class LibreOfficeConverter(Converter):
    name = "LibreOffice"

    def __init__(self, binary: str) -> None:
        self.binary = binary
        self._lock = threading.Lock()

    def to_pdf(self, docx: bytes) -> bytes:
        with self._lock, tempfile.TemporaryDirectory(prefix="careeros-soffice-") as tmp:
            source = Path(tmp) / "resume.docx"
            source.write_bytes(docx)
            subprocess.run([self.binary, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(source)],
                           check=True, capture_output=True, timeout=120)
            return (Path(tmp) / "resume.pdf").read_bytes()


_converter: Converter | None = None
_converter_lock = threading.Lock()


def _word_available() -> bool:
    if sys.platform != "win32" or os.environ.get("CAREEROS_DOCX_CONVERTER") == "libreoffice":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
        import win32com.client  # noqa: F401
        return True
    except (OSError, ImportError):
        return False


def get_converter() -> Converter:
    """The converter whose output defines page count and preview. Raises if none is installed."""
    global _converter
    with _converter_lock:
        if _converter is None:
            if _word_available():
                _converter = WordConverter()
            else:
                binary = shutil.which("soffice") or shutil.which("libreoffice")
                for candidate in (r"C:\Program Files\LibreOffice\program\soffice.exe",):
                    binary = binary or (candidate if Path(candidate).exists() else None)
                if not binary:
                    raise ConverterUnavailable(
                        "No DOCX layout engine found. Install Microsoft Word (Windows) or LibreOffice to measure "
                        "and preview the resume.")
                _converter = LibreOfficeConverter(binary)
        return _converter
