# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ryan Howell
"""Window tests. They need a display (they're skipped without one) and use a
throwaway data folder, so your own tapes are never touched."""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal as D

DATA = tempfile.mkdtemp(prefix="tallyforth-test-")
atexit.register(shutil.rmtree, DATA, True)
os.environ["XDG_DATA_HOME"] = DATA            # before tallyforth works out where tapes live

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

HAVE_DISPLAY = Gtk.init_check(None)[0]
if HAVE_DISPLAY:
    import tallyforth as tf  # noqa: E402
    import tapecore as tc  # noqa: E402
    tf.APP_ID = "com.example.TallyForthTest"


def labels(widget):
    out = []
    if isinstance(widget, Gtk.Label):
        out.append((widget.get_text(), widget.get_tooltip_text()))
    if isinstance(widget, Gtk.Container):
        for c in widget.get_children():
            out += labels(c)
    return out


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = tf.TallyForthApp()
        cls.app.register(None)

    def setUp(self):
        self.tapes = os.path.join(DATA, "tallyforth", "tapes")
        os.makedirs(self.tapes, exist_ok=True)
        for f in os.listdir(self.tapes):
            os.remove(os.path.join(self.tapes, f))

    def window(self):
        w = tf.TapeWindow(self.app)
        w.set_accept_focus(False)           # never take the keyboard from whoever is using the desktop
        self.addCleanup(w.destroy)
        return w

    def write_state(self, tapes, **extra):
        with open(os.path.join(DATA, "tallyforth", "state.json"), "w") as f:
            json.dump(dict({"tapes": tapes, "active": 0}, **extra), f)

    def test_huge_line_doesnt_stop_startup(self):
        with open(os.path.join(self.tapes, "big.json"), "w") as f:
            f.write(tc.dumps([tc.entry("num", "+", "1000000 × " * 5 + "1000000", "huge"),
                              tc.entry("num", "+", "5")], 2))
        self.write_state([{"id": "big", "title": "Big"}])
        w = self.window()
        self.assertEqual(w.tape.name(), "Big")
        self.assertEqual(w.tape.total, 5)

    def test_rows_update_like_a_full_redraw(self):
        self.write_state([])
        w = self.window()

        def check(what):
            fresh = []
            for e, r in zip(w.entries, tc.compute(w.entries, w.decimals)):
                row = w._make_row(e, r)
                row.set_figures(r)
                fresh.append(labels(row))
            self.assertEqual([labels(r) for r in w.listbox.get_children()], fresh, what)

        for note, amount in (("rent", "1200"), ("tax", "8%"), ("", "Σ÷2"), ("", "3 dozen eggs $12")):
            w.note.set_text(note)
            w.amount.set_text(amount)
            w.commit()
        check("typed")
        w.entries[0] = dict(w.entries[0], expr="1000")
        w._changed()
        check("edited the first line")
        w.delete_rows([1])
        check("deleted")
        w.move_lines([0], len(w.entries))
        check("moved")
        w.undo()
        check("undone")
        w.paste_lines("A 1.00\nB (2.00)")
        check("pasted")
        for mi in w.decimal_items:
            if mi.decimals_value == 0:
                mi.set_active(True)
        check("whole numbers")
        w.entries.insert(0, tc.entry("total"))
        w._changed()
        check("total at the top")

    def test_failed_save_asks_where_to_save(self):
        self.write_state([])
        w = self.window()
        w.amount.set_text("5")
        w.commit()
        w.path = os.path.join(DATA, "no-such-folder", "tape.tally")
        asked = []
        w.save_as = lambda: asked.append(True)
        w.save_tape()
        self.assertEqual(asked, [True])
        self.assertTrue(w.dirty)

    def test_flatpak_import_unlinks_unreachable_files(self):
        self.write_state([{"id": "a", "title": None, "path": "/home/someone/Budget.tally", "dirty": True},
                          {"id": "b", "title": "Mine", "path": None, "dirty": False}])
        tf.TapeWindow._forget_file_links(None)     # works on the state file alone
        with open(os.path.join(DATA, "tallyforth", "state.json")) as f:
            st = json.load(f)
        self.assertEqual([(t["title"], t["path"]) for t in st["tapes"]], [("Budget", None), ("Mine", None)])

    def test_sigma_key_then_plus(self):
        self.write_state([])
        w = self.window()
        w.amount.set_text("100")
        w.commit()
        w._keypad("Σ")
        w._keypad("+")                        # Σ alone: + is typed, not a line that doubles the total
        self.assertEqual(w.amount.get_text(), "Σ+")
        self.assertEqual(len(w.entries), 1)
        for key in "10.5%":
            w._keypad(key)
        w._keypad("+")
        self.assertEqual(w.entries[-1]["expr"], "10.5%")
        self.assertEqual(w.tape.total, D("110.5"))
        w.amount.set_text("Σ")
        self.assertFalse(w.commit())          # Enter on Σ alone explains instead
        self.assertIn("10.5%", w.status.get_text())
        self.assertEqual(len(w.entries), 2)

    def test_hash_key(self):
        from gi.repository import Gdk
        self.write_state([])
        w = self.window()

        def press(text):
            w.amount.set_text(text)
            w.amount.set_position(-1)
            ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
            ev.keyval, ev.state = Gdk.KEY_numbersign, 0
            return w._on_amount_key(w.amount, ev)

        w.amount.set_text("100")
        w.commit()
        self.assertTrue(press("Σ÷4"))                 # a calculation: # puts it on the tape as a side line
        self.assertEqual(w.entries[-1], tc.entry("side", "+", "Σ ÷ 4"))
        self.assertEqual(w.tape.total, 100)
        self.assertFalse(press("Check "))             # words: # is typed as usual
        self.assertEqual(len(w.entries), 2)

    def test_rename_follows_the_file(self):
        self.write_state([])
        w = self.window()
        w.rename(w.tape, "Party")                     # not saved yet: just the tab's name
        self.assertEqual(w.tape.name(), "Party")
        self.assertEqual(w._suggested_filename(), "Party.tally")

        folder = tempfile.mkdtemp(dir=DATA)
        w.amount.set_text("5")
        w.commit()
        w.path = os.path.join(folder, "Budget.tally")
        w.save_tape()
        self.assertEqual(w.tape.name(), "Budget")    # a saved tape goes by its file's name
        w.rename(w.tape, "2026 Budget")
        self.assertEqual(sorted(os.listdir(folder)), ["2026 Budget.tally"])
        self.assertEqual(w.tape.name(), "2026 Budget")
        self.assertEqual(w.tape.tab_text.get_text(), "2026 Budget")

        open(os.path.join(folder, "Taken.tally"), "w").close()
        w.rename(w.tape, "Taken")                     # never overwrites another file
        self.assertEqual(w.tape.name(), "2026 Budget")
        self.assertIn("already a file", w.status.get_text())

    def test_rename_in_flatpak_saves_a_copy(self):
        self.write_state([])
        w = self.window()
        w.path = os.path.join(DATA, "Budget.tally")
        asked = []
        w.save_as = lambda suggest=None: asked.append(suggest)
        tf.IN_FLATPAK = True
        try:
            w.rename(w.tape, "2026 Budget")
        finally:
            tf.IN_FLATPAK = False
        self.assertEqual(asked, ["2026 Budget.tally"])


if __name__ == "__main__":
    unittest.main()
