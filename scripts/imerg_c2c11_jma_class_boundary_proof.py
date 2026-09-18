"""C-2C-11 minimal JMA/IMERG class-comparison science proof.

RESEARCH ONLY.

This proof deliberately:
- reuses the frozen JMA precipitation classes;
- reuses the existing IMERG V07 canonical decoder;
- never invents midpoint rainfall values for JMA PNG classes;
- does not modify the production risk engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from lpz_risk.radar_science import JMA_PRECIPITATION_CLASSES


def continuous_mmph_to_jma_class_index(values: np.ndarray) -> np.ndarray:
    """Classify continuous non-negative rain rates using frozen JMA boundaries.

    Output:
      -1 = NaN / invalid / negative
       0..7 = frozen JMA precipitation class
    """

    arr = np.asarray(values, dtype=np.float64)

    result = np.full(arr.shape, -1, dtype=np.int8)

    valid = np.isfinite(arr) & (arr >= 0.0)

    for idx, precip_class in enumerate(JMA_PRECIPITATION_CLASSES):

        mask = valid & (arr >= precip_class.lower_mmph)

        if precip_class.upper_mmph is not None:
            mask &= arr < precip_class.upper_mmph

        result[mask] = idx

    return result


def run_boundary_proof() -> None:
    """Prove exact handling of all frozen class boundaries."""

    values = np.asarray(
        [
            np.nan,
            -1.0,
            0.0,
            0.999999,
            1.0,
            4.999999,
            5.0,
            9.999999,
            10.0,
            19.999999,
            20.0,
            29.999999,
            30.0,
            49.999999,
            50.0,
            79.999999,
            80.0,
            100.0,
        ],
        dtype=np.float64,
    )

    expected = np.asarray(
        [
            -1,
            -1,
            0,
            0,
            1,
            1,
            2,
            2,
            3,
            3,
            4,
            4,
            5,
            5,
            6,
            6,
            7,
            7,
        ],
        dtype=np.int8,
    )

    actual = continuous_mmph_to_jma_class_index(values)

    print("===== C-2C-11 CONTINUOUS -> JMA CLASS BOUNDARY PROOF =====")
    print()

    for value, got, want in zip(values, actual, expected):
        print(
            f"value={value!r:>10}  "
            f"actual={int(got):2d}  "
            f"expected={int(want):2d}"
        )

    print()

    if not np.array_equal(actual, expected):
        raise AssertionError(
            f"classification mismatch: actual={actual.tolist()} "
            f"expected={expected.tolist()}"
        )

    print("CLASS_COUNT =", len(JMA_PRECIPITATION_CLASSES))

    for idx, precip_class in enumerate(JMA_PRECIPITATION_CLASSES):
        print(
            idx,
            precip_class.class_id,
            precip_class.lower_mmph,
            precip_class.upper_mmph,
        )

    print()
    print("RESULT=PASS_C2C11_CONTINUOUS_TO_FROZEN_JMA_CLASS")
    print("RISK_ENGINE_ALLOWED=false")
    print("PRODUCTION_INTEGRATION_ALLOWED=false")


if __name__ == "__main__":
    run_boundary_proof()
