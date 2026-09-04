"""Counter-based randomness, so policy comparisons are actually paired.

The naive way to compare two policies is to run each against an identically
seeded simulator. It doesn't work: the policies take different actions, consume
draws from the shared stream in a different order, and by the second decision
the runs have diverged into different worlds. Any measured difference is then
part policy and part noise with no way to separate them.

The fix is common random numbers -- make every outcome a pure function of what
it's about, not when it was asked for. The k-th retry on payment P resolves
against uniform(seed, "auth", P, k): the same number whichever policy made that
retry and whatever it did beforehand. A policy that retries where another waited
sees exactly the world the other would have seen had it retried.

This is variance reduction, not a correctness trick. It doesn't bias the
comparison, it removes shared noise from it, so a real difference of a fraction
of a percent becomes visible without enormous samples.
"""

from __future__ import annotations

from hashlib import blake2b

_SCALE = float(1 << 64)


def uniform(seed: int, *keys: object) -> float:
    """A uniform draw on [0, 1) keyed by ``keys``.

    Deterministic and stateless: the same key always yields the same value,
    regardless of call order or how many draws preceded it.
    """
    h = blake2b(digest_size=8)
    h.update(str(seed).encode())
    for key in keys:
        h.update(b"\x1f")  # unit separator; prevents key-concatenation aliasing
        h.update(str(key).encode())
    return int.from_bytes(h.digest(), "big") / _SCALE


def bernoulli(p: float, seed: int, *keys: object) -> bool:
    return uniform(seed, *keys) < p


def choice(weights: dict, seed: int, *keys: object):
    """Weighted categorical draw. ``weights`` values must sum to 1.

    Iteration order of the mapping determines the partition of [0, 1), so the
    caller must pass a dict with stable ordering -- all of ours are module-level
    literals, which Python orders by insertion.
    """
    u = uniform(seed, *keys)
    cumulative = 0.0
    item = None
    for item, w in weights.items():
        cumulative += w
        if u < cumulative:
            return item
    return item  # float error on the final boundary


def exponential(mean: float, seed: int, *keys: object) -> float:
    """Exponential draw with the given mean."""
    from math import log
    u = uniform(seed, *keys)
    u = min(max(u, 1e-12), 1.0 - 1e-12)
    return -mean * log(1.0 - u)


def derive_seed(seed: int, *keys: object) -> int:
    """A sub-seed for components that need their own numpy Generator."""
    h = blake2b(digest_size=8)
    h.update(str(seed).encode())
    for key in keys:
        h.update(b"\x1f")
        h.update(str(key).encode())
    return int.from_bytes(h.digest(), "big")
