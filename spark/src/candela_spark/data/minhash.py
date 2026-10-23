import numpy as np
import xxhash

NUM_PERM = 112
BANDS = 14
ROWS = NUM_PERM // BANDS
SHINGLE = 5
MAX_WORDS = 2000
_PRIME = np.uint64((1 << 61) - 1)
_rng = np.random.default_rng(1729)
_A = _rng.integers(1, 1 << 31, size=NUM_PERM, dtype=np.uint64)
_B = _rng.integers(0, 1 << 31, size=NUM_PERM, dtype=np.uint64)
_MASK32 = np.uint64(0xFFFFFFFF)


def exact_hash(text: str) -> int:
    return xxhash.xxh64_intdigest(" ".join(text.lower().split()).encode())


def signature(text: str) -> np.ndarray:
    words = text.lower().split()[:MAX_WORDS]
    if len(words) < SHINGLE:
        words = words + [""] * (SHINGLE - len(words))
    wh = np.fromiter((xxhash.xxh32_intdigest(w.encode()) for w in words), dtype=np.uint64, count=len(words))
    n = len(words) - SHINGLE + 1
    sh = np.zeros(n, dtype=np.uint64)
    for k in range(SHINGLE):
        sh = sh * np.uint64(1_000_003) + wh[k : k + n]
    sh = (sh ^ (sh >> np.uint64(29))) & _MASK32
    hv = (sh[:, None] * _A[None, :] + _B[None, :]) % _PRIME
    return hv.min(axis=0).astype(np.uint32)


def band_hashes(sigs: np.ndarray) -> np.ndarray:
    out = np.empty((sigs.shape[0], BANDS), dtype=np.uint64)
    for b in range(BANDS):
        chunk = np.ascontiguousarray(sigs[:, b * ROWS : (b + 1) * ROWS])
        out[:, b] = [xxhash.xxh64_intdigest(row.tobytes(), seed=b) for row in chunk]
    return out
