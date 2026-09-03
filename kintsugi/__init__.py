"""Kintsugi: an expected-value agent for recovering failed payments.

Thread configuration, set before anything imports a BLAS or OpenMP runtime
-------------------------------------------------------------------------
The agent's workload is many thousands of *tiny* inference calls -- roughly
twenty candidate (moment, rail) rows scored per decision, several decisions per
payment -- rather than a few large batches. On batches that small, OpenMP's
per-call thread dispatch and synchronisation costs far more than the tree
traversal it is parallelising.

Measured on this project's retry model (195 trees, 43 features, 22-row batch):

    default thread pool     70.13 ms/call
    OMP_NUM_THREADS=1        2.50 ms/call     28x faster

which is the difference between a policy evaluation taking twenty-five minutes
and taking twenty-five seconds. The variables are set here, before the first
import of scikit-learn or NumPy, because OpenMP reads them once at
initialisation and ignores later changes. An explicit setting from the
environment is left alone.
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
