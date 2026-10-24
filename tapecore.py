# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ryan Howell
"""TallyForth core: the tape model, input parsing and arithmetic. No GTK here.

Each tape line that holds a number keeps its *working* (the expression as typed,
e.g. "3 × 12.50" or "Σ × 8%") and the result is worked out from it. Only "num"
lines feed the running total; "side" lines show a result without adding it.
"""

import csv
import io
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, getcontext

getcontext().prec = 34

SIGN = {"+": "+", "-": "−"}
DISPLAY = {"+": "+", "-": "−", "*": "×", "/": "÷"}

# kinds: "num" (result added to / subtracted from the running total),
# "side" (a calculation shown on the tape but not added), "note" (text only),
# "subtotal" (prints the running total), "total" (prints it and resets to zero)
KINDS = ("num", "side", "note", "subtotal", "total")


def entry(kind, op="+", expr="", note=""):
    return {"kind": kind, "op": op, "expr": expr, "note": note}


class ParseError(ValueError):
    pass


# ---------- tokens ----------
_TOKEN = re.compile(
    r"\s*(?:(?P<num>[$€£]?\s*(?:\d[\d,]*(?:\.\d*)?|\.\d+))|(?P<sum>Σ|sum\b)|(?P<op>[-+−*/×÷%()]))", re.I)
_OP_CANON = {"−": "-", "×": "*", "÷": "/"}
LIMIT = Decimal(10) ** 24   # bigger than any business sum; keeps rounding within Decimal's precision


def clean_number(s):
    """'$1,234.50' → '1234.50'. A single comma with one or two digits after it and
    no point is a decimal comma, the way most euro amounts are written: '5,50' → '5.50'."""
    s = re.sub(r"[$€£\s]", "", s)
    if "." not in s and re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    return s.replace(",", "").rstrip(".") or "0"


def tokenize(text):
    """Split text into expression tokens and whatever is left over (a note)."""
    toks, pos = [], 0
    while True:
        m = _TOKEN.match(text, pos)
        if not m:
            break
        if m.group("num"):
            toks.append(("num", clean_number(m.group("num"))))
        elif m.group("sum"):
            toks.append(("sum", "Σ"))
        else:
            toks.append(("op", _OP_CANON.get(m.group("op"), m.group("op"))))
        pos = m.end()
    return toks, text[pos:].strip()


def pretty(toks):
    """Render tokens the way the tape shows them: 3 × 12.50, Σ × 8%, (2 + 3) ÷ 4."""
    out, prev = "", None
    for kind, v in toks:
        binary = prev is not None and (prev[0] != "op" or prev[1] in ")%")
        if kind == "op" and v in "+-*/" and binary:
            out += f" {DISPLAY[v]} "
        elif kind == "op":
            out += DISPLAY.get(v, v)
        else:
            out += v
        prev = (kind, v)
    return out.strip()


# ---------- parsing ----------
class _Parser:
    """expr := term (+|- term)* ; term := factor (*|/ factor)* ;
    factor := (+|-) factor | primary %* ; primary := number | Σ | ( expr )"""

    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = ("bin", self.take()[1], node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek() in (("op", "*"), ("op", "/")):
            node = ("bin", self.take()[1], node, self.factor())
        return node

    def factor(self):
        if self.peek() in (("op", "+"), ("op", "-")):
            sign = self.take()[1]
            inner = self.factor()
            return ("neg", inner) if sign == "-" else inner
        node = self.primary()
        while self.peek() == ("op", "%"):
            self.take()
            node = ("pct", node)
        return node

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            try:
                return ("num", Decimal(val))
            except InvalidOperation:
                raise ParseError(f"bad number {val}")
        if kind == "sum":
            return ("sum",)
        if (kind, val) == ("op", "("):
            node = self.expr()
            if self.take() != ("op", ")"):
                raise ParseError("missing )")
            return node
        if kind is None:
            raise ParseError("unfinished calculation")
        raise ParseError(f"unexpected {DISPLAY.get(val, val)}")


def _parse_tokens(toks):
    p = _Parser(toks)
    node = p.expr()
    if p.i != len(toks):
        raise ParseError(f"unexpected {DISPLAY.get(p.peek()[1], p.peek()[1])}")
    return node


def _ev(node, sigma):
    k = node[0]
    if k == "num":
        return node[1]
    if k == "sum":
        return sigma
    if k == "neg":
        return -_ev(node[1], sigma)
    if k == "pct":
        return _ev(node[1], sigma) / 100
    _, op, a, b = node
    x = _ev(a, sigma)
    # Business-calculator percent: 200 + 8% is 216, 200 − 15% is 170.
    y = x * _ev(b, sigma) if (op in "+-" and b[0] == "pct") else _ev(b, sigma)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:
        raise ParseError("÷ by zero")
    return x / y


def evaluate(text, sigma=Decimal(0)):
    """Work out an expression. Σ is the running total; a bare percentage
    (e.g. "8%") means that percentage of the running total."""
    toks, rest = tokenize(text)
    if rest:
        raise ParseError(f"can't read “{rest}”")
    if not toks:
        raise ParseError("nothing to calculate")
    node = _parse_tokens(toks)
    bare = node[1] if node[0] == "neg" else node
    try:
        value = _ev(node, sigma)
        if bare[0] == "pct":
            value *= sigma
    except (InvalidOperation, OverflowError):
        raise ParseError("number too large")
    if abs(value) >= LIMIT:
        raise ParseError("number too large")
    return value


def tidy(text):
    """Check an expression and return it in tape form (raises ParseError)."""
    toks, rest = tokenize(text)
    if rest:
        raise ParseError(f"can't read “{rest}”")
    evaluate(pretty(toks), Decimal(1))
    return pretty(toks)


def is_calc(expr):
    """True if the working is worth showing (more than a plain number)."""
    return any(c in expr for c in "+×÷%()Σ") or "−" in expr.lstrip("−")


# ---------- input ----------
def parse_input(amount_text, note_text="", sigma=Decimal(0)):
    """Turn what the user typed into a tape entry, or None for nothing.

    "42", "-12.50", "3*12.50", "19.99 lunch", "8%" (of the running total),
    "Σ × 8%", "#Σ/2" or "=Σ/2" (side calculation), "t" (total), "s" (subtotal).
    """
    text = amount_text.strip()
    note = note_text.strip()
    low = text.lower()
    if low in ("t", "total"):
        return entry("total", note=note)
    if low in ("s", "sub", "subtotal"):
        return entry("subtotal", note=note)
    if not text:
        return entry("note", note=note) if note else None

    kind, op = "num", "+"
    signed = text[0] in "+-−"
    if text[0] in "=#":      # # is the adding machine's non-add key; = works too
        kind, text = "side", text[1:].strip()
    elif text[0] in "+-−":
        op, text = ("-" if text[0] in "-−" else "+"), text[1:].strip()

    toks, rest = tokenize(text)
    # "sum" followed by words is a note ("sum of receipts"), not Σ.
    if kind == "num" and rest and toks == [("sum", "Σ")] and re.match(r"sum\b", text, re.I):
        toks, rest = [], text
    if kind == "num" and (not toks or rest):
        # When words come before a figure at the end, that figure is the amount:
        # "Potato salad $55", "3 dozen eggs $12", "Tip 15%".
        for m in re.finditer(r"\s(?=\S)", text):
            tail = text[m.end():]
            t_toks, t_rest = tokenize(tail)
            if t_toks and not t_rest:
                try:
                    e = parse_input(tail, (text[:m.start()].strip() + " " + note).strip(), sigma)
                except ParseError:
                    continue
                if e and e["kind"] == "num":
                    if op == "-":
                        e["op"] = "-" if e["op"] == "+" else "+"
                    return e
    # "12 - refund": a dangling operator belongs to the note, not the sum.
    while rest and toks and toks[-1][0] == "op" and toks[-1][1] in "+-*/(":
        rest = DISPLAY.get(toks[-1][1], toks[-1][1]) + " " + rest
        toks.pop()
    if not toks:
        if kind == "num" and op == "+" and amount_text.strip()[0] not in "+":
            return entry("note", note=(amount_text.strip() + " " + note).strip())
        raise ParseError("nothing to calculate")
    short = _sigma_plus(toks) if kind == "num" and not signed else None
    if short:
        op, toks = short
    expr = pretty(toks)
    evaluate(expr, sigma)
    return entry(kind, op, expr, (rest.strip() + " " + note).strip())


def _sigma_plus(toks):
    """On a tally line, "Σ + 10.5%" means "the total plus 10.5%", so the line to add
    is 10.5% (adding Σ itself would count the total twice). Returns (op, the rest's
    tokens), or None when the line isn't Σ plus or minus one more term."""
    if len(toks) < 3 or toks[0] != ("sum", "Σ") or toks[1] not in (("op", "+"), ("op", "-")):
        return None
    try:
        node = _parse_tokens(toks[2:])
    except ParseError:
        return None
    if node[0] == "bin" and node[1] in "+-":      # Σ − 15% + 2 isn't the same as − (15% + 2)
        return None
    return toks[1][1], toks[2:]


# ---------- the tape ----------
def round_to(d, decimals):
    """Round half-up (2.345 → 2.35), the way receipts and invoices do. None = keep exact."""
    if decimals is None:
        return d
    try:
        return d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    except InvalidOperation:     # too many digits to round; show it as it is rather than fail
        return d


def compute(entries, decimals=None):
    """Walk the tape and return per-row results.

    With `decimals` set, every line is rounded to that many places before it is
    added, so the printed lines always add up to the printed totals.

    Each result: {"shown": figure printed on the row, "running": total after it,
    "sigma": the running total the row's Σ refers to, "count", "error"}.
    """
    total = Decimal(0)
    count = 0
    out = []
    for e in entries:
        r = {"running": None, "shown": None, "sigma": None, "error": None, "count": None}
        k = e["kind"]
        if k in ("num", "side"):
            r["sigma"] = total
            try:
                v = evaluate(e["expr"], total)
            except ParseError as ex:
                r["error"] = str(ex)
                out.append(r)
                continue
            v = round_to(v, decimals)
            r["shown"] = v
            if k == "num":
                total = total + v if e.get("op", "+") == "+" else total - v
                count += 1
                r["running"] = total
        elif k in ("subtotal", "total"):
            r["shown"] = total
            r["running"] = total
            r["count"] = count
            if k == "total":
                total = Decimal(0)
                count = 0
        out.append(r)
    return out


def current_total(entries, decimals=None):
    return total_after(entries, compute(entries, decimals))


def total_after(entries, results):
    """The running total at the end of the tape, from compute()'s results."""
    for e, r in zip(reversed(entries), reversed(results)):
        if e["kind"] == "total":
            return Decimal(0)
        if r["running"] is not None:
            return r["running"]
    return Decimal(0)


def fmt(d, decimals):
    if d is None:
        return ""
    if decimals is None:
        s = format(d.normalize(), ",f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    q = round_to(d, decimals)
    s = f"{q:,.{decimals}f}"
    return s[1:] if s.startswith("-") and q == 0 else s


def to_text(entries, decimals, width=56):
    """Render the tape as plain text."""
    lines = []
    for e, r in zip(entries, compute(entries, decimals)):
        k = e["kind"]
        note = e.get("note", "")
        if k == "note":
            lines.append(note)
            continue
        if k in ("num", "side"):
            work = (e["expr"] + " = ") if is_calc(e["expr"]) else ""
            sym = "#" if k == "side" else SIGN[e["op"]]
            fig = f"ERR {r['error']}" if r["error"] else fmt(r["shown"], decimals)
            right = f"{work}{fig} {sym}"
        elif k == "subtotal":
            right = fmt(r["shown"], decimals) + " ◇"
        else:
            lines.append("-" * width)
            right = fmt(r["shown"], decimals) + " T"
        space = width - len(right) - 1
        lines.append((note[:space] if space > 0 else "").ljust(max(space, 0)) + " " + right)
        if k == "total":
            lines.append("=" * width)
            lines.append("")
    return "\n".join(lines) + "\n"


def to_csv(entries, decimals):
    """The tape as CSV for spreadsheets: one row per line, amounts signed
    (subtractions negative) and plain (no thousands separators)."""
    def num(d):
        return "" if d is None else format(round_to(d, decimals), "f")
    def text(v):
        # Spreadsheets run a cell starting with = + - @ as a formula; a leading ' keeps it text.
        return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
    kinds = {"num": "item", "side": "side calculation", "note": "note", "subtotal": "subtotal", "total": "total"}
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(["Line", "Type", "Note", "Working", "Amount", "Balance"])
    for n, (e, r) in enumerate(zip(entries, compute(entries, decimals)), 1):
        k = e["kind"]
        amount = r["shown"]
        if k == "num" and amount is not None and e.get("op") == "-":
            amount = -amount
        work = e.get("expr", "") if k in ("num", "side") and is_calc(e.get("expr", "")) else ""
        if r["error"]:
            work = f"{work} (error: {r['error']})".strip()
        out.writerow([n, kinds[k], text(e.get("note", "")), text(work), num(amount),
                      num(r["running"]) if k == "num" else ""])
    return buf.getvalue()


# A money figure: -45.23, $1,234.56, (45.23) for negative, 55.
_MONEY = r"[-−+]?\s*[$€£]?\s*\(?\s*[$€£]?\d[\d,]*(?:\.\d*)?\s*\)?"


def _split_figures(line):
    """Peel the money figures off the end of a line: ("COSTCO", ["-45.23", "1,209.77"])."""
    figs = []
    while True:
        m = re.search(r"(?:^|\s)(" + _MONEY + r")$", line)
        if not m:
            return line.strip(), figs
        figs.insert(0, m.group(1).strip())
        line = line[:m.start(1)]


def _figure(fig):
    """A pasted figure as (op, digits): '(12.00)' → ('-', '12.00')."""
    neg = fig.lstrip().startswith(("-", "−")) or ("(" in fig and ")" in fig)
    return ("-" if neg else "+"), clean_number(re.sub(r"[^\d.,]", "", fig))


def _signed(fig):
    op, digits = _figure(fig)
    return -Decimal(digits) if op == "-" else Decimal(digits)


def _balance_column(rows):
    """True when the last figure on every line is a running balance (bank and card
    exports put one after the amount): each balance differs from the one before
    by that line's amount, whether the list runs oldest or newest first."""
    rows = [figs for _, figs in rows if figs]
    if len(rows) < 2 or any(len(figs) < 2 for figs in rows):
        return False
    try:
        bal = [_signed(f[-1]) for f in rows]
        amt = [abs(_signed(f[-2])) for f in rows]
    except InvalidOperation:
        return False
    return all(abs(bal[i] - bal[i - 1]) in (amt[i], amt[i - 1]) for i in range(1, len(rows)))


def parse_pasted(text):
    """Turn a pasted list (from a spreadsheet, statement, email…) into tape lines.

    Each line's last money figure becomes the amount and the rest its note:
    "Potato salad<TAB>$55.00", "10/12  COSTCO  -45.23", "Fees (12.00)".
    If every line ends with amount then running balance, as statements do, the
    balance is dropped. A line that starts with the amount works too
    ("12.50 parking"), and a line with no number at all becomes a note line.
    Blank lines are skipped.
    """
    rows = []
    for raw in text.splitlines():
        line = " ".join(raw.replace("\t", "  ").split())
        if not line:
            continue
        note, figs = _split_figures(line)
        if not figs:
            m = re.match(r"^(" + _MONEY + r")(?:\s+(.*))?$", line)
            if m:
                note, figs = (m.group(2) or "").strip(), [m.group(1).strip()]
        rows.append((note, figs))
    drop = 1 if _balance_column(rows) else 0
    out = []
    for note, figs in rows:
        if not figs:
            out.append(entry("note", note=note))
            continue
        keep = figs[:len(figs) - drop]
        op, digits = _figure(keep[-1])
        out.append(entry("num", op, digits, " ".join([note] + keep[:-1]).strip()))
    return out


def move_lines(entries, indices, to):
    """Move the lines at `indices` (kept in their order) so they sit just before
    position `to` of the original tape (len(entries) means the end).
    Returns (new_entries, new_indices of the moved lines)."""
    picked = sorted({i for i in indices if 0 <= i < len(entries)})
    moving = [entries[i] for i in picked]
    rest = [e for i, e in enumerate(entries) if i not in set(picked)]
    at = max(0, min(to, len(entries))) - sum(1 for i in picked if i < to)
    return rest[:at] + moving + rest[at:], list(range(at, at + len(moving)))


# ---------- files ----------
def dumps(entries, decimals):
    return json.dumps({"app": "tallyforth", "version": 2, "decimals": decimals, "entries": entries}, indent=2)


def _upgrade_v1(e):
    """Version 1 kept a bare value and let × and ÷ rewrite the whole running total.
    Re-express those lines so every total comes out the same as before."""
    v = pretty(tokenize(str(e.get("value", "0")))[0]) or "0"
    op = e.get("op", "+")
    if op == "*":
        return entry("num", "+", f"Σ × {v} − Σ", e.get("note", ""))
    if op == "/":
        return entry("num", "+", f"Σ ÷ {v} − Σ", e.get("note", ""))
    return entry("num", op, v, e.get("note", ""))


def loads(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
        raise ValueError("this isn't a TallyForth tape")
    entries = []
    for e in data.get("entries", []):
        if not isinstance(e, dict):
            continue
        e = dict(e, note=str(e.get("note") or ""))
        k = e.get("kind")
        if k not in KINDS:
            continue
        if k == "num" and "expr" not in e:
            entries.append(_upgrade_v1(e))
        else:
            op = e.get("op", "+") if e.get("op") in ("+", "-") else "+"
            entries.append(entry(k, op, str(e.get("expr", "")), e.get("note", "")))
    dec = data.get("decimals", 2)
    return entries, (dec if dec is None or (type(dec) is int and 0 <= dec <= 8) else 2)
