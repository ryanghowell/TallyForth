# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ryan Howell
import csv
import io
import json
import unittest
from decimal import Decimal as D

import tapecore as tc


class ParseTests(unittest.TestCase):
    def p(self, a, n="", sigma=D(0)):
        return tc.parse_input(a, n, sigma)

    def test_plain_number_adds(self):
        self.assertEqual(self.p("42"), tc.entry("num", "+", "42"))

    def test_leading_sign(self):
        self.assertEqual(self.p("-12.50"), tc.entry("num", "-", "12.50"))
        self.assertEqual(self.p("−5")["op"], "-")
        self.assertEqual(self.p("+5")["op"], "+")

    def test_working_is_kept(self):
        e = self.p("3*12.50 sandwiches")
        self.assertEqual((e["expr"], e["note"]), ("3 × 12.50", "sandwiches"))
        self.assertEqual(self.p("(2+3)/4")["expr"], "(2 + 3) ÷ 4")
        self.assertEqual(self.p("sum*8%")["expr"], "Σ × 8%")
        self.assertEqual(self.p("3×-2")["expr"], "3 × −2")

    def test_notes(self):
        self.assertEqual(self.p("19.99 lunch", "with Sam")["note"], "lunch with Sam")
        self.assertEqual(self.p("", "March receipts"), tc.entry("note", note="March receipts"))
        self.assertEqual(self.p("groceries")["kind"], "note")
        self.assertEqual(self.p("12 xmas lights")["note"], "xmas lights")
        self.assertEqual(self.p("12 t-shirts")["note"], "t-shirts")
        e = self.p("12 - refund")
        self.assertEqual((e["expr"], e["note"]), ("12", "− refund"))
        self.assertIsNone(self.p("", ""))

    def test_currency_signs(self):
        self.assertEqual(self.p("$55."), tc.entry("num", "+", "55"))
        self.assertEqual(self.p("$1,250.00")["expr"], "1250.00")
        self.assertEqual(self.p("-$12")["op"], "-")
        self.assertEqual(self.p("3 × $4.50")["expr"], "3 × 4.50")
        self.assertEqual(self.p("€20")["expr"], "20")

    def test_note_first(self):
        self.assertEqual(self.p("Potato Salad $55."), tc.entry("num", "+", "55", "Potato Salad"))
        self.assertEqual(self.p("Rolls 3×4.50"), tc.entry("num", "+", "3 × 4.50", "Rolls"))
        self.assertEqual(self.p("Tip 15%", sigma=D(100))["expr"], "15%")
        self.assertEqual(self.p("Chips $4", "Costco")["note"], "Chips Costco")
        self.assertEqual(self.p("Room 101 keys")["kind"], "note")   # number in the middle: just a note
        self.assertEqual(self.p("Potato salad")["kind"], "note")

    def test_commas(self):
        self.assertEqual(self.p("1,250.00")["expr"], "1250.00")

    def test_side_and_totals(self):
        self.assertEqual(self.p("=Σ/2")["kind"], "side")
        self.assertEqual(self.p("T")["kind"], "total")
        self.assertEqual(self.p("s", "so far"), tc.entry("subtotal", note="so far"))

    def test_errors(self):
        for bad in ("4/0", "3*", "((2", "=", "2*)", "-"):
            with self.assertRaises(tc.ParseError, msg=bad):
                self.p(bad)
        with self.assertRaises(tc.ParseError):
            self.p("100/sum", sigma=D(0))
        self.assertEqual(self.p("100/sum", sigma=D(4))["expr"], "100 ÷ Σ")


class MathTests(unittest.TestCase):
    def ev(self, s, sigma=0):
        return tc.evaluate(s, D(sigma))

    def test_basics(self):
        self.assertEqual(self.ev("0.1+0.2"), D("0.3"))
        self.assertEqual(self.ev("2+3*4"), 14)
        self.assertEqual(self.ev("(2+3)*4"), 20)
        self.assertEqual(self.ev("-3*-2"), 6)

    def test_percent(self):
        self.assertEqual(self.ev("200+8%"), 216)
        self.assertEqual(self.ev("200-15%"), 170)
        self.assertEqual(self.ev("200*8%"), 16)
        self.assertEqual(self.ev("50/50%"), 100)
        self.assertEqual(self.ev("8%", sigma=500), 40)        # bare % = % of running total
        self.assertEqual(self.ev("Σ×8%", sigma=500), 40)
        self.assertEqual(self.ev("Σ+10%", sigma=500), 550)
        self.assertEqual(self.ev("(8%)", sigma=500), 40)

    def test_tidy(self):
        self.assertEqual(tc.tidy("3*12.5"), "3 × 12.5")
        with self.assertRaises(tc.ParseError):
            tc.tidy("3 apples")


class TapeTests(unittest.TestCase):
    def test_items_side_and_totals(self):
        es = [tc.entry("num", "+", "3 × 12.50", "sandwiches"), tc.entry("num", "+", "4.99"),
              tc.entry("num", "+", "Σ × 8%", "tax"), tc.entry("subtotal"),
              tc.entry("side", "+", "Σ ÷ 2", "each"), tc.entry("num", "-", "10"),
              tc.entry("total"), tc.entry("num", "+", "1")]
        r = tc.compute(es)
        self.assertEqual(r[0]["running"], D("37.50"))
        self.assertEqual(r[2]["sigma"], D("42.49"))
        self.assertEqual(r[2]["shown"], D("3.3992"))
        self.assertEqual((r[3]["shown"], r[3]["count"]), (D("45.8892"), 3))
        self.assertEqual(r[4]["shown"], D("22.9446"))
        self.assertIsNone(r[4]["running"])                      # side calc doesn't add
        self.assertEqual(r[6]["count"], 4)
        self.assertEqual(r[6]["shown"], D("35.8892"))
        self.assertEqual(tc.current_total(es), 1)
        self.assertEqual(tc.current_total(es[:5]), D("45.8892"))

    def test_bad_row_is_skipped(self):
        r = tc.compute([tc.entry("num", "+", "5"), tc.entry("num", "+", "1 ÷ (Σ − 5)"), tc.entry("total")])
        self.assertEqual(r[1]["error"], "÷ by zero")
        self.assertEqual(r[2]["shown"], 5)

    def test_is_calc(self):
        self.assertFalse(tc.is_calc("12.50"))
        self.assertFalse(tc.is_calc("−5"))
        self.assertTrue(tc.is_calc("3 × 2"))
        self.assertTrue(tc.is_calc("8%"))
        self.assertTrue(tc.is_calc("5 − 2"))

    def test_fmt(self):
        self.assertEqual(tc.fmt(D("1234.5"), 2), "1,234.50")
        self.assertEqual(tc.fmt(D("-0.001"), 2), "0.00")
        self.assertEqual(tc.fmt(D("2.50"), None), "2.5")
        self.assertEqual(tc.fmt(D("7.6"), 0), "8")

    def test_roundtrip_and_text(self):
        es = [tc.entry("note", note="Trip"), tc.entry("num", "+", "3 × 4", "gas"),
              tc.entry("side", "+", "Σ ÷ 2", "each"), tc.entry("total", note="Done")]
        self.assertEqual(tc.loads(tc.dumps(es, 2)), (es, 2))
        txt = tc.to_text(es, 2)
        self.assertIn("3 × 4 = 12.00 +", txt)
        self.assertIn("Σ ÷ 2 = 6.00 =", txt)
        self.assertIn("12.00 T", txt)


class RoundingTests(unittest.TestCase):
    def test_lines_add_up_to_the_total(self):
        # Three lines of 8% tax on 42.49 each are 3.3992 exactly; printed as 3.40.
        es = [tc.entry("num", "+", "42.49")] + [tc.entry("num", "+", "42.49 × 8%")] * 3 + [tc.entry("total")]
        r = tc.compute(es, 2)
        self.assertEqual([x["shown"] for x in r[1:4]], [D("3.40")] * 3)
        self.assertEqual(r[4]["shown"], D("52.69"))           # 42.49 + 3 × 3.40, not 52.6876
        self.assertEqual(tc.to_text(es, 2).count("3.40 +"), 3)

    def test_sigma_is_the_rounded_total(self):
        es = [tc.entry("num", "+", "10 ÷ 3"), tc.entry("num", "+", "10 ÷ 3"), tc.entry("side", "+", "Σ")]
        self.assertEqual(tc.compute(es, 2)[2]["shown"], D("6.66"))

    def test_half_up(self):
        self.assertEqual(tc.round_to(D("2.345"), 2), D("2.35"))
        self.assertEqual(tc.round_to(D("2.5"), 0), D("3"))
        self.assertEqual(tc.round_to(D("-2.345"), 2), D("-2.35"))
        self.assertEqual(tc.fmt(D("2.345"), 2), "2.35")

    def test_as_entered_keeps_everything(self):
        es = [tc.entry("num", "+", "10 ÷ 4")]
        self.assertEqual(tc.compute(es, None)[0]["shown"], D("2.5"))
        self.assertEqual(tc.compute(es, 0)[0]["shown"], D("3"))


class PasteTests(unittest.TestCase):
    def test_paste_shapes(self):
        es = tc.parse_pasted("Potato salad\t$55.00\n\n10/12/2026  COSTCO  -45.23\n"
                             "Fees (12.00)\n12.50 parking\nDescription  Amount\nChips 4\n$1,234.56\n")
        self.assertEqual(es, [
            tc.entry("num", "+", "55.00", "Potato salad"),
            tc.entry("num", "-", "45.23", "10/12/2026 COSTCO"),
            tc.entry("num", "-", "12.00", "Fees"),
            tc.entry("num", "+", "12.50", "parking"),
            tc.entry("note", note="Description Amount"),
            tc.entry("num", "+", "4", "Chips"),
            tc.entry("num", "+", "1234.56", ""),
        ])

    def test_numbers_inside_text_stay_in_the_note(self):
        self.assertEqual(tc.parse_pasted("Room 101 keys"), [tc.entry("note", note="Room 101 keys")])
        self.assertEqual(tc.parse_pasted("Order 66 total 19.99"), [tc.entry("num", "+", "19.99", "Order 66 total")])


class CsvTests(unittest.TestCase):
    def test_csv(self):
        es = [tc.entry("note", note="Trip"), tc.entry("num", "+", "1250"), tc.entry("num", "-", "3 × 2.50", "refund, partial"),
              tc.entry("side", "+", "Σ ÷ 2", "each"), tc.entry("total")]
        rows = list(csv.reader(io.StringIO(tc.to_csv(es, 2))))
        self.assertEqual(rows[0], ["Line", "Type", "Note", "Working", "Amount", "Balance"])
        self.assertEqual(rows[1], ["1", "note", "Trip", "", "", ""])
        self.assertEqual(rows[2], ["2", "item", "", "", "1250.00", "1250.00"])
        self.assertEqual(rows[3], ["3", "item", "refund, partial", "3 × 2.50", "-7.50", "1242.50"])
        self.assertEqual(rows[4], ["4", "side calculation", "each", "Σ ÷ 2", "621.25", ""])
        self.assertEqual(rows[5], ["5", "total", "", "", "1242.50", ""])


class MoveTests(unittest.TestCase):
    def notes(self, es):
        return "".join(e["note"] for e in es)

    def test_moves(self):
        es = [tc.entry("note", note=n) for n in "abcde"]
        self.assertEqual(tc.move_lines(es, [3], 1), ([es[0], es[3], es[1], es[2], es[4]], [1]))
        self.assertEqual(self.notes(tc.move_lines(es, [0], 5)[0]), "bcdea")
        self.assertEqual(self.notes(tc.move_lines(es, [1, 2], 5)[0]), "adebc")
        self.assertEqual(self.notes(tc.move_lines(es, [1, 3], 0)[0]), "bdace")   # gathered together
        self.assertEqual(tc.move_lines(es, [2], 2)[0], es)                       # dropped on itself
        self.assertEqual(tc.move_lines(es, [2], 3)[0], es)

    def test_recalculates(self):
        es = [tc.entry("num", "+", "100"), tc.entry("num", "+", "Σ × 10%", "tax"), tc.entry("num", "+", "50")]
        self.assertEqual(tc.compute(es)[1]["shown"], 10)
        moved, _ = tc.move_lines(es, [2], 1)          # put the 50 above the tax line
        self.assertEqual(tc.compute(moved)[2]["shown"], 15)
        self.assertEqual(tc.current_total(moved), 165)


class UpgradeTests(unittest.TestCase):
    def test_v1_tapes_keep_their_totals(self):
        v1 = {"app": "papertape", "version": 1, "decimals": 2, "entries": [
            {"kind": "num", "op": "+", "value": "10", "note": "a"},
            {"kind": "num", "op": "+", "value": "20", "note": ""},
            {"kind": "num", "op": "*", "value": "3", "note": "triple"},
            {"kind": "num", "op": "-", "value": "15", "note": ""},
            {"kind": "num", "op": "/", "value": "2", "note": "split"},
            {"kind": "total", "op": "+", "value": "", "note": ""}]}
        es, dec = tc.loads(json.dumps(v1))
        self.assertEqual(es[2], tc.entry("num", "+", "Σ × 3 − Σ", "triple"))
        r = tc.compute(es)
        self.assertEqual(r[2]["running"], 90)                    # old: (10+20)×3
        self.assertEqual(r[5]["shown"], D("37.5"))              # old: (90−15)÷2


class ReviewFixTests(unittest.TestCase):
    """Bugs found in the pre-release review."""

    def test_huge_numbers_are_refused_not_fatal(self):
        with self.assertRaises(tc.ParseError):
            tc.parse_input("1000000×1000000×1000000×1000000×1000000×1000000")
        # A line like that saved by an older version shows an error instead of crashing.
        r = tc.compute([tc.entry("num", "+", "1" + "0" * 40), tc.entry("num", "+", "5")], 2)
        self.assertEqual(r[0]["error"], "number too large")
        self.assertEqual(r[1]["running"], 5)
        self.assertEqual(tc.round_to(D("1e40"), 4), D("1e40"))   # too long to round: left as is

    def test_quantity_before_the_amount(self):
        cases = {"3 dozen eggs $12": ("12", "3 dozen eggs"), "2 boxes of paper 30": ("30", "2 boxes of paper"),
                 "Potato salad $55": ("55", "Potato salad"), "19.99 lunch": ("19.99", "lunch"),
                 "3 × 12.50 lunch": ("3 × 12.50", "lunch"), "12 - refund": ("12", "− refund")}
        for text, (expr, note) in cases.items():
            e = tc.parse_input(text)
            self.assertEqual((e["expr"], e["note"]), (expr, note), text)
        self.assertEqual(tc.parse_input("-Refund 20"), tc.entry("num", "-", "20", "Refund"))

    def test_decimal_comma(self):
        self.assertEqual(tc.parse_input("€5,50")["expr"], "5.50")
        self.assertEqual(tc.parse_input("1,5")["expr"], "1.5")
        self.assertEqual(tc.parse_input("1,234")["expr"], "1234")          # thousands, as before
        self.assertEqual(tc.parse_input("1,234.56")["expr"], "1234.56")
        self.assertEqual(tc.parse_pasted("Café 4,20")[0]["expr"], "4.20")

    def test_statement_balance_column_is_dropped(self):
        statement = ("10/12/2026  COSTCO  -45.23  1,209.77\n"
                     "10/13/2026  PAYROLL  2,000.00  3,209.77\n"
                     "10/14/2026  GAS  -40.00  3,169.77\n")
        got = [(e["op"], e["expr"], e["note"]) for e in tc.parse_pasted(statement)]
        self.assertEqual(got, [("-", "45.23", "10/12/2026 COSTCO"), ("+", "2000.00", "10/13/2026 PAYROLL"),
                               ("-", "40.00", "10/14/2026 GAS")])
        newest_first = "\n".join(reversed(statement.strip().splitlines()))
        self.assertEqual([e["expr"] for e in tc.parse_pasted(newest_first)], ["40.00", "2000.00", "45.23"])
        # Two figures that aren't a running balance: keep the last, as before.
        es = tc.parse_pasted("Eggs 3 4.00\nMilk 2 3.00")
        self.assertEqual([(e["expr"], e["note"]) for e in es], [("4.00", "Eggs 3"), ("3.00", "Milk 2")])

    def test_sum_as_a_word(self):
        self.assertEqual(tc.parse_input("sum of receipts 40", "", D(100))["expr"], "40")
        self.assertEqual(tc.parse_input("sum for lunch", "", D(100)), tc.entry("note", note="sum for lunch"))
        self.assertEqual(tc.parse_input("sum × 2")["expr"], "Σ × 2")        # still Σ in a calculation
        self.assertEqual(tc.parse_input("Σ lunch")["expr"], "Σ")

    def test_files_that_arent_tapes(self):
        for text in ("[]", '"hello"', '{"entries": 5}'):
            with self.assertRaises(ValueError):
                tc.loads(text)
        es, dec = tc.loads('{"decimals": 40, "entries": [7, {"kind": "note", "note": 55}, {"kind": "num"}]}')
        self.assertEqual(es, [tc.entry("note", note="55"), tc.entry("num", expr="0")])
        self.assertEqual(dec, 2)
        self.assertEqual(tc.loads('{"decimals": true, "entries": []}')[1], 2)

    def test_csv_notes_are_not_formulas(self):
        rows = list(csv.reader(io.StringIO(tc.to_csv(
            [tc.entry("num", "+", "5", "+1 guest"), tc.entry("note", note="=HYPERLINK(1)"),
             tc.entry("num", "+", "2", "plain")], 2))))
        self.assertEqual([r[2] for r in rows[1:]], ["'+1 guest", "'=HYPERLINK(1)", "plain"])


if __name__ == "__main__":
    unittest.main()
