"""The eval's own scoring rules, on examples small enough to compute by hand."""

from evals.metrics import (
    calibration_error,
    f1,
    header_correct,
    match_lines,
    normalize_field,
    percentile,
    real_header_correct,
)


def line(description, quantity, unit_price, amount_minor):
    return {"description": description, "quantity": quantity, "unit_price": unit_price, "amount_minor": amount_minor}


GOLD = [line("Torque wrench 40-200 Nm", "4", "89.50", 35800), line("Socket set 1/2 inch", "2", "124.00", 24800),
        line("Safety goggles, anti-fog", "10", "6.20", 6200)]


def test_hungarian_pairs_lines_regardless_of_order():
    predicted = [GOLD[2], GOLD[0], GOLD[1]]  # same lines, shuffled
    score = match_lines(GOLD, predicted)
    assert score.true_positives == 3
    assert sorted((g, p) for g, p, _, _ in score.pairs) == [(0, 1), (1, 2), (2, 0)]


def test_best_overall_pairing_beats_greedy():
    # Greedy would give gold 0 the predicted line it likes most ("Torque wrench set"), leaving gold 1 a poor match.
    # The optimal pairing keeps both correct.
    gold = [line("Torque wrench", "1", "10", 1000), line("Torque wrench set", "1", "20", 2000)]
    predicted = [line("Torque wrench set", "1", "20", 2000), line("Torque wrench", "1", "10", 1000)]
    assert match_lines(gold, predicted).true_positives == 2


def test_small_wording_differences_still_match_but_wrong_numbers_dont():
    predicted = [line("TORQUE WRENCH 40–200Nm", "4", "89.5", 35800),   # dash, case, spacing: same line
                 line("Socket set 1/2 inch", "2", "124.00", 24900),   # amount wrong
                 line("Safety goggles, anti-fog", "10", "6.20", 6200)]
    score = match_lines(GOLD, predicted)
    assert score.true_positives == 2
    assert [ok for _, _, _, ok in sorted(score.pairs)] == [True, False, True]


def test_missing_and_extra_lines_count_against_recall_and_precision():
    score = match_lines(GOLD, [GOLD[0], line("Delivery fee", "1", "15.00", 1500)])
    # One right of 2 predicted, one of 3 gold found: F1 = 2 * (1/2 * 1/3) / (1/2 + 1/3) = 0.4
    assert (score.true_positives, score.predicted, score.gold) == (1, 2, 3)
    assert round(f1(1, 2, 3), 6) == 0.4
    assert f1(0, 0, 0) == 1.0 and f1(0, 3, 0) == 0.0


def test_calibration_counts_only_confident_fields():
    observations = [(0.99, True), (0.95, False), (0.90, True), (0.92, True), (0.5, False), (0.89, False)]
    error, n = calibration_error(observations)
    assert n == 4 and error == 0.25  # 1 wrong of the 4 at ≥ 0.9; the 0.5 and 0.89 don't count
    assert calibration_error([(0.3, False)]) == (0.0, 0)


def test_header_normalization():
    gold = {"vendor_name": "ACME Werkzeuge GmbH", "vendor_tax_id": "DE812345678", "po_number": "4500100001",
            "invoice_date": "2026-09-15", "currency": "EUR", "total_minor": 35700}
    predicted = {"vendor_name": "  acme  werkzeuge gmbh", "vendor_tax_id": "DE 812 345 678", "po_number": "PO 4500100001",
                 "invoice_date": "2026-09-15", "currency": "eur", "total_minor": 35700}
    correct = header_correct(gold, predicted)
    assert all(correct[f] for f in gold)
    assert correct["due_date"] and correct["invoice_number"]  # both missing on both sides
    assert normalize_field("invoice_number", "RE-2026-0915") != normalize_field("invoice_number", "RE-2026-915")


def test_nearest_rank_percentile():
    assert percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 95) == 100
    assert percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 50) == 50
    assert percentile([], 95) == 0.0


def test_real_invoices_check_only_what_the_line_prints():
    # One layout prints an amount per aired spot, another a spot count and a rate with no line amount.
    per_spot = [{"description": "Fox 9 AM News at 6am", "quantity": None, "unit_price": None, "amount_minor": 12500}]
    count_rate = [{"description": "CHANNEL 11 NEWS", "quantity": "4", "unit_price": "625.00", "amount_minor": None}]
    assert match_lines(per_spot, [line("Fox 9 AM News at 6am", "1", "125.00", 12500)], only_printed=True).true_positives == 1
    assert match_lines(count_rate, [line("CHANNEL 11 NEWS", "4", "625", 250000)], only_printed=True).true_positives == 1
    assert match_lines(count_rate, [line("CHANNEL 11 NEWS", "5", "625", 312500)], only_printed=True).true_positives == 0
    assert match_lines(count_rate, [line("CHANNEL 11 NEWS", "4", "625", 250000)]).true_positives == 0  # strict: amount differs


def test_real_invoice_total_may_be_gross_or_net():
    gold = {"invoice_number": "950658", "invoice_date": "2020-02-23", "total_minor_accepted": [478125, 562500]}
    assert real_header_correct(gold, {"invoice_number": "950658", "invoice_date": "2020-02-23", "total_minor": 562500}) == \
        {"invoice_number": True, "invoice_date": True, "total_minor": True}
    assert real_header_correct(gold, {"total_minor": 478125})["total_minor"]
    assert not real_header_correct(gold, {"total_minor": 500000})["total_minor"]
    assert real_header_correct({"invoice_number": None, "invoice_date": None, "total_minor_accepted": []}, {}) == \
        {"invoice_number": True, "invoice_date": True, "total_minor": True}  # a non-invoice: nothing invented


def test_real_invoice_lines_tolerate_extra_columns_and_repeated_descriptions():
    # The model folds air dates and spot codes into the description; per-spot invoices repeat one description.
    gold = [{"description": "SPOT 9:00:00AM- 5:00:00 Day,M-4", "quantity": None, "unit_price": None, "amount_minor": 1000},
            {"description": "SPOT 9:00:00AM- 5:00:00 Day,M-4", "quantity": None, "unit_price": None, "amount_minor": 2000}]
    got = [line("SPOT 9:00:00AM- 5:00:00 Day,M-4 03/02/20 9:23AM (Mo) 00:30 MMT130", "1", "20.00", 2000),
           line("SPOT 9:00:00AM- 5:00:00 Day,M-4 03/02/20 9:59AM (Mo) 00:15 MMT115", "1", "10.00", 1000)]
    assert match_lines(gold, got, only_printed=True).true_positives == 2
    assert match_lines(gold, got).true_positives == 0  # the strict rule for generated invoices is unchanged

