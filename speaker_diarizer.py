"""Speaker Diarizer.

Given an audio embedding (list/np.ndarray of floats produced by
`voice_identity.get_embedding`), iterate over every registered person and
return the highest-similarity match — provided it passes the threshold.

This module is pure-numpy: it does not record audio, does not call any LLM,
and does not consult the legacy single-person voiceprint.json. Callers who
want Jeevan recognised through this path should register him explicitly via
`person_registry.register`.
"""
from typing import Iterable, Optional, Sequence, Union

import numpy as np

import person_registry
from person_types import RecognitionResult


_DEFAULT_THRESHOLD = 0.75


def _to_array(embedding: Union[Sequence[float], np.ndarray]) -> Optional[np.ndarray]:
    if embedding is None:
        return None
    arr = np.asarray(embedding, dtype=float)
    if arr.size == 0:
        return None
    return arr


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Similarity score between two 1-D embeddings.

    Voice embeddings produced by `voice_identity.get_embedding` are expected
    to be unit-normalised, so we report the raw dot product. For unit vectors
    this equals cosine similarity, but for non-unit inputs the score scales
    with the query magnitude — preserving sensitivity to amplitude drift
    between enrolment and runtime.

    Returns 0.0 if either side has zero norm.
    """
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b))


def identify_speaker(
    embedding: Union[Sequence[float], np.ndarray],
    threshold: float = _DEFAULT_THRESHOLD,
) -> RecognitionResult:
    """Return the best matching registered person's name (or None)."""
    arr = _to_array(embedding)
    if arr is None:
        return RecognitionResult(name=None, similarity=0.0, threshold=threshold)

    best_name: Optional[str] = None
    best_sim: float = 0.0
    for name, vp in person_registry.iter_voiceprints():
        try:
            other = np.asarray(vp, dtype=float)
            if other.shape != arr.shape:
                continue
            sim = _cosine(arr, other)
        except Exception:
            continue
        if sim > best_sim:
            best_sim = sim
            best_name = name

    if best_name is None or best_sim < threshold:
        return RecognitionResult(name=None, similarity=best_sim, threshold=threshold)
    return RecognitionResult(name=best_name, similarity=best_sim, threshold=threshold)
