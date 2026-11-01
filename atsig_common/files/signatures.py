"""Recognizes the allowed upload types from the first bytes of a file."""

# A PDF header may be preceded by a few bytes (a BOM, a line of text): readers
# accept it anywhere in the first KB, so we do too.
PDF_HEADER_WINDOW = 1024
SIGNATURE_BYTES = PDF_HEADER_WINDOW

EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def detect_file_type(head: bytes) -> str | None:
    """
    Returns the content type the bytes say the file has, or None if it is not
    allowed. The header of the client says what it wants; only the bytes say what
    the file is. Read the first SIGNATURE_BYTES of the file and pass them here.
    """
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b"%PDF-" in head[:PDF_HEADER_WINDOW]:
        return "application/pdf"
    return None
