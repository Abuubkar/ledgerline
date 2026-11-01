"""How extraction and agent results are scored against the golden set. Plain functions on plain data, so each rule
can be tested on hand-computed examples (evals/tests/test_metrics.py).

- Header fields: exact match after normalizing what doesn't change the meaning (case and spacing in names,
  separators in tax IDs and PO numbers). Dates are compared as ISO strings and amounts in minor units.
- Line items: predicted and gold lines are paired with the Hungarian algorithm (the pairing that maximizes total
  description similarity); a pair counts as correct when the descriptions are at least 85% similar and quantity,
  unit price and amount are all equal. Precision, recall and F1 follow from those counts.
- Calibration: among fields the model said it was at least 90% sure of, the share it got wrong.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np
from rapidfuzz import fuzz, utils
from scipy.optimize import linear_sum_assignment

from ledgerline_api.normalize import normalize_tax_id, po_number_key

HEADER_FIELDS = ("vendor_name", "vendor_tax_id", "invoice_number", "po_number", "invoice_date", "due_date", "currency",
                 "subtotal_minor", "tax_minor", "total_minor")
DESCRIPTION_SIMILARITY = 85
CONFIDENT = 0.9


def _text(value) -> str | None:
    return " ".join(str(value).split()).casefold() if value not in (None, "") else None


def normalize_field(name: str, value):
    """The form two values of a header field are compared in."""
    if value in (None, ""):
        return None
    if name == "vendor_tax_id":
        return normalize_tax_id(str(value)) or None
    if name == "po_number":
        return po_number_key(str(value))
    if name in ("subtotal_minor", "tax_minor", "total_minor"):
        return int(value)
    if name in ("invoice_date", "due_date"):
        return str(value)[:10]
    if name == "currency":
        return str(value).upper()
    return _text(value)


def header_correct(gold: dict, predicted: dict) -> dict[str, bool]:
    return {name: normalize_field(name, gold.get(name)) == normalize_field(name, predicted.get(name)) for name in HEADER_FIELDS}


# The real-invoice set (evals/golden/real) prints no tax ID, PO or tax, so it's scored on these three. Its invoices
# print a gross total and a net after agency commission; either is a correct "total".
REAL_FIELDS = ("invoice_number", "invoice_date", "total_minor")


def real_header_correct(gold: dict, predicted: dict) -> dict[str, bool]:
    correct = {name: normalize_field(name, gold.get(name)) == normalize_field(name, predicted.get(name))
               for name in ("invoice_number", "invoice_date")}
    total = predicted.get("total_minor")
    correct["total_minor"] = total in gold["total_minor_accepted"] if total is not None else not gold["total_minor_accepted"]
    return correct


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value)).normalize() if value not in (None, "") else None
    except InvalidOperation:
        return None


@dataclass
class LineScore:
    true_positives: int
    predicted: int
    gold: int
    pairs: list[tuple[int, int, float, bool]]  # (gold index, predicted index, similarity, correct)

    @property
    def precision(self) -> float:
        return self.true_positives / self.predicted if self.predicted else (1.0 if not self.gold else 0.0)

    @property
    def recall(self) -> float:
        return self.true_positives / self.gold if self.gold else (1.0 if not self.predicted else 0.0)


def similarity(a: str | None, b: str | None) -> float:
    return fuzz.token_sort_ratio(a or "", b or "", processor=utils.default_process)


def match_lines(gold: list[dict], predicted: list[dict], only_printed: bool = False) -> LineScore:
    """Pair predicted lines with gold lines and count the pairs that are right in every value.

    only_printed is for real invoices (evals/golden/real): a value the invoice doesn't print (None in gold: some
    layouts print an amount per spot, others count × rate) isn't checked; a description counts when the gold's words
    are all in the extracted one (models fold neighbouring columns such as air dates into it); and lines whose numbers
    agree are paired first, since per-spot invoices repeat the same description many times."""
    if not gold or not predicted:
        return LineScore(0, len(predicted), len(gold), [])

    def numbers_agree(gl: dict, pl: dict) -> bool:
        checks = (("quantity", _decimal), ("unit_price", _decimal), ("amount_minor", lambda v: v))
        return all((only_printed and gl.get(key) is None) or norm(gl.get(key)) == norm(pl.get(key)) for key, norm in checks)

    def describe(g: dict, p: dict) -> float:
        if only_printed:
            return fuzz.token_set_ratio(g.get("description") or "", p.get("description") or "", processor=utils.default_process)
        return similarity(g.get("description"), p.get("description"))

    scores = np.array([[describe(g, p) for p in predicted] for g in gold])
    pairing = scores + np.array([[100 * numbers_agree(g, p) for p in predicted] for g in gold]) if only_printed else scores
    rows, cols = linear_sum_assignment(pairing, maximize=True)
    pairs, correct = [], 0
    for g, p in zip(rows, cols):
        ok = scores[g, p] >= DESCRIPTION_SIMILARITY and numbers_agree(gold[g], predicted[p])
        correct += ok
        pairs.append((int(g), int(p), float(scores[g, p]), bool(ok)))
    return LineScore(correct, len(predicted), len(gold), pairs)


def f1(true_positives: int, predicted: int, gold: int) -> float:
    """Micro-averaged F1 over every line in the set."""
    if not predicted and not gold:
        return 1.0
    precision = true_positives / predicted if predicted else 0.0
    recall = true_positives / gold if gold else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def calibration_error(observations: list[tuple[float, bool]]) -> tuple[float, int]:
    """(share wrong, how many) among (confidence, correct) observations at or above CONFIDENT. 0.0 with none."""
    confident = [correct for confidence, correct in observations if confidence >= CONFIDENT]
    if not confident:
        return 0.0, 0
    return sum(not c for c in confident) / len(confident), len(confident)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile: the smallest value with at least pct% of values at or below it."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(np.ceil(pct / 100 * len(ordered))))
    return ordered[rank - 1]
