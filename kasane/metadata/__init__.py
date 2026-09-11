"""入力画像のメタデータ読取り（FITS / DSLR RAW）"""

from .reader import read_frame, read_frames, is_supported, RAW_EXTENSIONS, FITS_EXTENSIONS

__all__ = ["read_frame", "read_frames", "is_supported", "RAW_EXTENSIONS", "FITS_EXTENSIONS"]
