def is_key_under_prefix(key: str, prefix: str) -> bool:
    """
    True when the storage key is a plain key below the prefix (which ends with "/").
    Dot or empty segments, backslashes, percent signs and control characters are
    refused: a key the app writes never has them, and refusing them means the check
    does not depend on how the storage or an HTTP layer reads such a key.

    Use this for every check of a prefix. A bare `key.startswith(prefix)` accepts
    `applications/1/../2/file`.
    """
    if not prefix.endswith("/") or not key.startswith(prefix):
        return False
    if any(ch in key for ch in ("\\", "%")) or any(
        ord(ch) < 32 or ord(ch) == 127 for ch in key
    ):
        return False
    return all(segment not in ("", ".", "..") for segment in key.split("/"))
