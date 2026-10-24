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


def tokenize(text):
    """Split text into expression tokens and whatever is left over (a note)."""
    toks, pos = [], 0
    while True:
        m = _TOKEN.match(text, pos)
        if not m:
            break
        if m.group("num"):
            toks.append(("num", re.sub(r"[$€£,\s]", "", m.group("num")).rstrip(".") or "0"))
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
        return value
    except (InvalidOperation, OverflowError):
        raise ParseError("number too large")


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
    "Σ × 8%", "=Σ/2" (side calculation), "t" (total), "s" (subtotal).
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
    if text[0] == "=":
        kind, text = "side", text[1:].strip()
    elif text[0] in "+-−":
        op, text = ("-" if text[0] in "-−" else "+"), text[1:].strip()

    toks, rest = tokenize(text)
    if not toks and kind == "num" and op == "+":
        # Note first, amount last: "Potato salad $55", "Tip 15%".
        for m in re.finditer(r"\s(?=\S)", text):
            tail = text[m.end():]
            t_toks, t_rest = tokenize(tail)
            if t_toks and not t_rest:
                try:
                    return parse_input(tail, (text[:m.start()].strip() + " " + note).strip(), sigma)
                except ParseError:
                    continue
    # "12 - refund": a dangling operator belongs to the note, not the sum.
    while rest and toks and toks[-1][0] == "op" and toks[-1][1] in "+-*/(":
        rest = DISPLAY.get(toks[-1][1], toks[-1][1]) + " " + rest
        toks.pop()
    if not toks:
        if kind == "num" and op == "+" and amount_text.strip()[0] not in "+":
            return entry("note", note=(amount_text.strip() + " " + note).strip())
        raise ParseError("nothing to calculate")
    expr = pretty(toks)
    evaluate(expr, sigma)
    return entry(kind, op, expr, (rest.strip() + " " + note).strip())


# ---------- the tape ----------
def round_to(d, decimals):
    """Round half-up (2.345 → 2.35), the way receipts and invoices do. None = keep exact."""
    if decimals is None:
        return d
    return d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


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
    for e, r in zip(reversed(entries), reversed(compute(entries, decimals))):
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
            sym = "=" if k == "side" else SIGN[e["op"]]
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
        out.writerow([n, kinds[k], e.get("note", ""), work, num(amount),
                      num(r["running"]) if k == "num" else ""])
    return buf.getvalue()


# A money figure: -45.23, $1,234.56, (45.23) for negative, 55.
_MONEY = r"[-−+]?\s*[$€£]?\s*\(?\s*[$€£]?\d[\d,]*(?:\.\d*)?\s*\)?"


def parse_pasted(text):
    """Turn a pasted list (from a spreadsheet, statement, email…) into tape lines.

    Each line's last money figure becomes the amount and the rest its note:
    "Potato salad<TAB>$55.00", "10/12  COSTCO  -45.23", "Fees (12.00)".
    A line that starts with the amount works too ("12.50 parking"), and a
    line with no number at all becomes a note line. Blank lines are skipped.
    """
    out = []
    for raw in text.splitlines():
        line = " ".join(raw.replace("\t", "  ").split())
        if not line:
            continue
        m = re.search(r"(?:^|\s)(" + _MONEY + r")$", line)
        if m:
            fig, note = m.group(1), line[:m.start(1)].strip()
        else:
            m = re.match(r"^(" + _MONEY + r")(?:\s+(.*))?$", line)
            if not m:
                out.append(entry("note", note=line))
                continue
            fig, note = m.group(1), (m.group(2) or "").strip()
        neg = fig.lstrip().startswith(("-", "−")) or ("(" in fig and ")" in fig)
        digits = re.sub(r"[^\d.]", "", fig).rstrip(".") or "0"
        out.append(entry("num", "-" if neg else "+", digits, note))
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
    entries = []
    for e in data.get("entries", []):
        k = e.get("kind")
        if k not in KINDS:
            continue
        if k == "num" and "expr" not in e:
            entries.append(_upgrade_v1(e))
        else:
            op = e.get("op", "+") if e.get("op") in ("+", "-") else "+"
            entries.append(entry(k, op, str(e.get("expr", "")), e.get("note", "")))
    dec = data.get("decimals", 2)
    return entries, (dec if dec is None or isinstance(dec, int) else 2)
