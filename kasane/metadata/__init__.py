"""入力画像のメタデータ読取り（FITS / DSLR RAW）"""

from .reader import read_frame, read_frames, is_supported, is_nonlinear, RAW_EXTENSIONS, FITS_EXTENSIONS, NONLINEAR_EXTENSIONS

__all__ = ["read_frame", "read_frames", "is_supported", "is_nonlinear", "RAW_EXTENSIONS", "FITS_EXTENSIONS", "NONLINEAR_EXTENSIONS"]
