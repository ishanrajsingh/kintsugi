"""Kintsugi: an expected-value agent for recovering failed payments.

Thread limits are set here, before anything imports a BLAS or OpenMP runtime.

The workload is many thousands of *tiny* inference calls -- about twenty
candidate (moment, rail) rows per decision, several decisions per payment --
rather than a few large batches. At that size OpenMP's per-call dispatch and
synchronisation costs far more than the tree traversal it's parallelising.

Measured on the retry model (195 trees, 43 features, 22-row batch):

    default thread pool     70.13 ms/call
    OMP_NUM_THREADS=1        2.50 ms/call     28x faster

which is a policy evaluation taking twenty-five seconds instead of twenty-five
minutes. It has to happen before the first scikit-learn or NumPy import because
OpenMP reads these once at init and ignores later changes. An explicit setting
from the environment is left alone.
"""

from __future__ import annotations

import os

for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_var, "1")

del _var, os

__version__ = "1.0.0"
