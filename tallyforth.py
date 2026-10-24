#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""TallyForth: a tape calculator with notes alongside the numbers.

Copyright (C) 2026 Ryan Howell
This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License, version 3 or (at your option) any
later version. It comes with ABSOLUTELY NO WARRANTY; see the LICENSE file.
"""

import copy
import json
import os
import shutil
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath: works when run via a symlink
import tapecore as tc  # noqa: E402

VERSION = "0.1.0"
APP_ID = "io.github.ryanghowell.TallyForth"
WEBSITE = "https://github.com/ryanghowell/TallyForth"
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "tallyforth")
# Where earlier copies kept their tapes, copied over on first run: a non-Flatpak install
# (seen from inside the Flatpak sandbox) and the app from when it was called "Paper Tape".
HOST_DATA_DIR = os.path.expanduser("~/.local/share/tallyforth") if os.environ.get("FLATPAK_ID") else None
OLD_DATA_DIRS = [d for d in (HOST_DATA_DIR, os.path.join(GLib.get_user_data_dir(), "papertape")) if d]
AUTOSAVE = os.path.join(DATA_DIR, "autosave.json")   # the single tape, before tabs
TAPES_DIR = os.path.join(DATA_DIR, "tapes")           # one autosave file per tab
STATE = os.path.join(DATA_DIR, "state.json")
ZOOM_STEPS = (0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5)

CSS = b"""
.tape { background: #fbf8ee; font-family: monospace; font-size: 12pt; color: #2b2b2b; }
.tape row { padding: 1px 14px; background: transparent; }
.tape row:selected { background: #ecdfa8; color: #2b2b2b; }
.tape row:selected label { color: #2b2b2b; }
.tape .note { color: #3a4f7a; font-style: italic; }
.tape .amount { font-weight: normal; }
.tape .neg { color: #b3261e; }
.tape .op { color: #777; }
.tape .running { color: #a39e90; font-size: 9pt; }
.tape .work { color: #5d6b8a; font-size: 11pt; }
.tape .side-amt { color: #5d6b8a; font-style: italic; }
.tape .error { color: #b3261e; font-weight: bold; }
.tape .sub-row { border-top: 1px dotted #b8b1a0; }
.tape .total-row { border-top: 1px solid #555; border-bottom: 3px double #555; padding-top: 3px; padding-bottom: 3px; margin-bottom: 14px; }
.tape .total-row .amount { font-weight: bold; }
.tape .count { color: #a39e90; font-size: 9pt; }
.tape .grip { color: #ddd6c2; }
.tape row:hover .grip, .tape row:selected .grip { color: #8a8270; }
.tape row.drop-before { box-shadow: inset 0 3px #3a6ea5; }
.tape row.drop-after { box-shadow: inset 0 -3px #3a6ea5; }
.empty-hint { color: #a39e90; font-style: italic; padding: 30px; }
.display { font-family: monospace; font-size: 20pt; font-weight: bold; padding: 4px 10px; }
.display.neg { color: #b3261e; }
.amount-entry { font-family: monospace; font-size: 14pt; }
.keypad button { font-family: monospace; font-size: 14pt; min-width: 52px; min-height: 40px; }
.keypad .op-key { font-weight: bold; color: #3a4f7a; }
.keypad .plus-key { font-weight: bold; font-size: 20pt; color: #3a4f7a; }
.keypad .key-word { font-weight: normal; font-size: 8pt; }
.keypad .plus-key .key-word { font-size: 10pt; }
.keypad .fn-key { font-size: 11pt; color: #666; }
.keypad .side-key { font-weight: bold; color: #5d6b8a; }
"""

HELP = """<b>Adding up</b>
<tt>42</tt> then <tt>+</tt> or <tt>Enter</tt>   add 42 to the tally
<tt>42</tt> then <tt>−</tt>            subtract 42
<tt>3×12.50</tt> then <tt>+</tt>      work it out and add the result; the tape keeps the working
note, <tt>Tab</tt>, amount   e.g. <tt>Potato salad</tt> Tab <tt>$55</tt> Enter ($ is fine)
<tt>Potato salad $55</tt>  typed all in the amount box works too
note only, <tt>Enter</tt>   write a note line
<tt>+</tt> and <tt>−</tt> finish a line, so put sums inside one line in brackets: <tt>(2+3)×4</tt>

<b>Percentages and the running total</b>
<tt>8%</tt> then <tt>+</tt>           add 8% of the running total (tax, tip)
<tt>15%</tt> then <tt>−</tt>          take 15% off the running total (discount)
<tt>200+8%</tt>         216: a percentage of the number before it
<tt>Σ</tt> (or type <tt>sum</tt>)    the running total so far, e.g. <tt>Σ÷3</tt> then <tt>=</tt>
<tt>Σ+10.5%</tt> then <tt>+</tt>  same as <tt>10.5%</tt> then <tt>+</tt>: the total plus 10.5% tax

<b>Side calculations</b>
<tt>Σ÷2</tt> then <tt>=</tt>          show an answer on the tape without adding it
Right-click it → Add to Tally   count it after all

<b>Pasting a list</b>
Copy a column from a spreadsheet, a bank statement or an email and press <tt>Ctrl+V</tt>:
each line's amount goes on the tape with the rest of the line as its note.
<tt>Ctrl+Shift+V</tt> pastes as a list even when it's a single line.

<b>Tapes (tabs)</b>
<tt>Ctrl+T</tt> new tape    <tt>Ctrl+W</tt> close    <tt>Ctrl+PgUp</tt> / <tt>Ctrl+PgDn</tt> switch
Double-click a tab to rename it; drag tabs to reorder

<b>Totals</b>
<tt>s</tt> or <tt>◇</tt>           subtotal: print the total so far, keep counting
<tt>t</tt> or <tt>T</tt>           total: print it, then start a fresh tally

<b>Working with the tape</b>
Double-click a line    edit it (totals below update)
Drag across lines      select several at once
Drag a line's <tt>⠿</tt> grip   move it (or all selected lines); totals redo themselves
<tt>Alt+↑</tt> / <tt>Alt+↓</tt>          move the selected lines up or down
Shift+click / Ctrl+click  extend the selection / pick lines
Right-click a line     edit, add a note above, delete
<tt>Delete</tt>          remove the selected lines
<tt>Ctrl+Z</tt> / <tt>Ctrl+Shift+Z</tt>  undo / redo
<tt>Ctrl+O</tt>  open    <tt>Ctrl+S</tt>  save    <tt>Ctrl++</tt> / <tt>Ctrl+−</tt> / <tt>Ctrl+0</tt>  zoom (or Ctrl+wheel)
<tt>Ctrl+K</tt>  show or hide the keypad    <tt>F11</tt>  full screen    <tt>F1</tt>  this help
<tt>Ctrl+Shift+C</tt>  copy the tape as text
Everything is autosaved, so closing never loses the tape."""


class EditDialog(Gtk.Dialog):
    KINDS = (("+", "+  add to the tally"), ("-", "−  subtract from the tally"),
             ("=", "=  side calculation (not added)"))

    def __init__(self, parent, e, title):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.e = e
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        self.get_content_area().add(grid)
        row = 0
        self.op_combo = self.expr_entry = None
        if e["kind"] in ("num", "side"):
            self.expr_entry = Gtk.Entry(text=e["expr"], activates_default=True)
            self.expr_entry.get_style_context().add_class("amount-entry")
            self.expr_entry.set_tooltip_text("A number or a calculation, e.g. 3×12.50, Σ×8%, (2+3)÷4")
            grid.attach(Gtk.Label(label="Working", xalign=1), 0, row, 1, 1)
            grid.attach(self.expr_entry, 1, row, 1, 1)
            row += 1
            self.op_combo = Gtk.ComboBoxText()
            for k, label in self.KINDS:
                self.op_combo.append(k, label)
            self.op_combo.set_active_id("=" if e["kind"] == "side" else e["op"])
            grid.attach(Gtk.Label(label="Result", xalign=1), 0, row, 1, 1)
            grid.attach(self.op_combo, 1, row, 1, 1)
            row += 1
        self.note_entry = Gtk.Entry(text=e.get("note", ""), activates_default=True, width_chars=36)
        grid.attach(Gtk.Label(label="Note", xalign=1), 0, row, 1, 1)
        grid.attach(self.note_entry, 1, row, 1, 1)
        self.err = Gtk.Label(xalign=0)
        grid.attach(self.err, 1, row + 1, 1, 1)
        self.show_all()
        (self.expr_entry or self.note_entry).grab_focus()

    def result(self):
        """Run until valid input or cancel. Returns the edited entry or None."""
        while self.run() == Gtk.ResponseType.OK:
            e = dict(self.e)
            e["note"] = self.note_entry.get_text().strip()
            if self.expr_entry is not None:
                try:
                    e["expr"] = tc.tidy(self.expr_entry.get_text())
                except tc.ParseError as ex:
                    self.err.set_markup(f"<span foreground='#b3261e'>Can't work that out ({GLib.markup_escape_text(str(ex))})</span>")
                    continue
                choice = self.op_combo.get_active_id()
                e["kind"], e["op"] = ("side", "+") if choice == "=" else ("num", choice)
            self.destroy()
            return e
        self.destroy()
        return None


class Tape:
    """One tab: its lines, file, decimal setting, undo history and tape widgets."""

    def __init__(self, entries=None, decimals=2, path=None, dirty=False, title=None, tid=None):
        self.entries = entries if entries is not None else []
        self.decimals, self.path, self.dirty, self.title = decimals, path, dirty, title
        self.id = tid or GLib.uuid_string_random().replace("-", "")[:12]
        self.undo_stack, self.redo_stack = [], []
        self.total = tc.Decimal(0)      # running total at the end, kept up to date by refresh()
        self.scroller = self.listbox = self.tab_text = None

    def name(self):
        if self.title:
            return self.title
        if self.path:
            return os.path.splitext(os.path.basename(self.path))[0]
        return "Untitled"


def _on_tape(name):
    """A window attribute that really belongs to the tape in the front tab."""
    return property(lambda self: getattr(self.tape, name), lambda self, v: setattr(self.tape, name, v))


class TapeWindow(Gtk.ApplicationWindow):
    entries = _on_tape("entries")
    decimals = _on_tape("decimals")
    path = _on_tape("path")
    dirty = _on_tape("dirty")
    undo_stack = _on_tape("undo_stack")
    redo_stack = _on_tape("redo_stack")
    listbox = _on_tape("listbox")
    scroller = _on_tape("scroller")

    def __init__(self, app):
        super().__init__(application=app, title="TallyForth")
        self.set_default_size(470, 860)
        self.tape = None
        self.tapes = []
        self.zoom = 1.0
        self._loading = True

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.zoom_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.zoom_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

        # No set_titlebar(): Cinnamon's window manager draws the title bar and its
        # minimize / maximize / close buttons, the same as every other app.
        self._build_body()
        self._load_state()
        self._loading = False
        if self._first_run_save:              # write the tabs layout out once
            for t in self.tapes:
                self.tape, keep = t, self.tape
                self._autosave()
                self.tape = keep
        self.connect("delete-event", self._on_close)
        self.refresh(scroll_to_end=True)
        self.note.grab_focus()

    # ---------- layout ----------
    def _build_menubar(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        bar = Gtk.MenuBar()
        C, S = Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK

        def menu(title):
            top = Gtk.MenuItem.new_with_mnemonic(title)
            sub = Gtk.Menu(accel_group=accel)
            top.set_submenu(sub)
            bar.append(top)
            return sub

        def item(m, label, cb, key=None, mods=C, widget=None):
            mi = widget or Gtk.MenuItem.new_with_mnemonic(label)
            mi.connect("activate", lambda *_: cb())
            if key:
                mi.add_accelerator("activate", accel, key, mods, Gtk.AccelFlags.VISIBLE)
            m.append(mi)
            return mi

        def selected(fn):
            def run():
                rows = self.selected_indices()
                if not rows:
                    self.flash("Click a line on the tape first")
                else:
                    fn(rows[0])
            return run

        f = menu("_File")
        new = item(f, "_New Tape", self.new_tape, Gdk.KEY_t)
        new.add_accelerator("activate", accel, Gdk.KEY_n, C, Gtk.AccelFlags(0))
        item(f, "_Open…", self.open_tape, Gdk.KEY_o)
        item(f, "_Save", self.save_tape, Gdk.KEY_s)
        item(f, "Save _As…", self.save_as, Gdk.KEY_s, C | S)
        f.append(Gtk.SeparatorMenuItem())
        item(f, "_Rename Tape…", lambda: self.rename_tape(self.tape))
        item(f, "_Close Tape", lambda: self.close_tape(self.tape), Gdk.KEY_w)
        f.append(Gtk.SeparatorMenuItem())
        item(f, "_Export as Text…", self.export_text, Gdk.KEY_e)
        item(f, "Export as _CSV…", self.export_csv)
        f.append(Gtk.SeparatorMenuItem())
        item(f, "_Quit", self.close, Gdk.KEY_q)

        e = menu("_Edit")
        item(e, "_Undo", self.undo, Gdk.KEY_z)
        redo = item(e, "_Redo", self.redo, Gdk.KEY_z, C | S)
        redo.add_accelerator("activate", accel, Gdk.KEY_y, C, Gtk.AccelFlags(0))
        e.append(Gtk.SeparatorMenuItem())
        item(e, "_Copy Tape as Text", self.copy_text, Gdk.KEY_c, C | S)
        item(e, "_Paste List of Numbers", self.paste_clipboard_list, Gdk.KEY_v, C | S)
        e.append(Gtk.SeparatorMenuItem())
        item(e, "_Edit Selected Line…", selected(self.edit_row))
        item(e, "Add _Note Above Selected…", selected(self.insert_note_above))
        item(e, "_Delete Selected Lines", lambda: self.delete_rows(self.selected_indices()))
        item(e, "Select _All Lines", self.listbox_select_all)
        e.append(Gtk.SeparatorMenuItem())
        item(e, "Move Lines _Up", lambda: self.move_selected(-1), Gdk.KEY_Up, Gdk.ModifierType.MOD1_MASK)
        item(e, "Move Lines Do_wn", lambda: self.move_selected(1), Gdk.KEY_Down, Gdk.ModifierType.MOD1_MASK)

        v = menu("_View")
        self.keypad_item = Gtk.CheckMenuItem.new_with_mnemonic("Show _Keypad")
        self.keypad_item.connect("toggled", lambda mi: (self.keypad.set_visible(mi.get_active()), self._autosave()))
        self.keypad_item.add_accelerator("activate", accel, Gdk.KEY_k, C, Gtk.AccelFlags.VISIBLE)
        v.append(self.keypad_item)
        self.fullscreen_item = Gtk.CheckMenuItem.new_with_mnemonic("_Full Screen")
        self.fullscreen_item.connect("toggled", lambda mi: self.fullscreen() if mi.get_active() else self.unfullscreen())
        self.fullscreen_item.add_accelerator("activate", accel, Gdk.KEY_F11, 0, Gtk.AccelFlags.VISIBLE)
        v.append(self.fullscreen_item)
        v.append(Gtk.SeparatorMenuItem())
        zin = item(v, "Zoom _In", lambda: self.set_zoom(+1), Gdk.KEY_plus)
        zin.add_accelerator("activate", accel, Gdk.KEY_equal, C, Gtk.AccelFlags(0))
        zin.add_accelerator("activate", accel, Gdk.KEY_KP_Add, C, Gtk.AccelFlags(0))
        zout = item(v, "Zoom _Out", lambda: self.set_zoom(-1), Gdk.KEY_minus)
        zout.add_accelerator("activate", accel, Gdk.KEY_KP_Subtract, C, Gtk.AccelFlags(0))
        item(v, "_Actual Size", lambda: self.set_zoom(0), Gdk.KEY_0)
        v.append(Gtk.SeparatorMenuItem())
        item(v, "Ne_xt Tape", lambda: self.notebook.next_page(), Gdk.KEY_Page_Down)
        item(v, "Pre_vious Tape", lambda: self.notebook.prev_page(), Gdk.KEY_Page_Up)
        # Keep the check mark honest if the window manager changes the state (e.g. Esc, a keyboard shortcut).
        self.connect("window-state-event", lambda w, ev: self.fullscreen_item.set_active(
            bool(ev.new_window_state & Gdk.WindowState.FULLSCREEN)) or False)
        v.append(Gtk.SeparatorMenuItem())
        group = None
        for label, val in (("_Whole Numbers", 0), ("_2 Decimal Places", 2), ("_4 Decimal Places", 4),
                           ("As _Entered", None)):
            mi = Gtk.RadioMenuItem.new_with_mnemonic_from_widget(group, label)
            group = mi
            mi.decimals_value = val
            mi.connect("toggled", self._on_decimals)
            v.append(mi)
        self.decimal_items = group.get_group()

        h = menu("_Help")
        item(h, "_Keyboard Shortcuts", self.show_help, Gdk.KEY_F1, 0)
        item(h, "_About TallyForth", self.show_about)
        return bar

    def _build_body(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)
        vbox.pack_start(self._build_menubar(), False, False, 0)

        self._move = None        # while dragging lines by their grip: {"lines": [...], "to": index}
        self._marked = None      # (row, css class) of the drop marker being shown
        self._grab_cursor = False
        self._drag_anchor, self._dragging, self._drag_from_blank = None, False, False

        self.notebook = Gtk.Notebook(scrollable=True, show_border=False)
        self.notebook.connect("switch-page", self._on_switch_page)
        self.notebook.connect("page-reordered", lambda *_: self._save_state())
        plus = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU)
        plus.set_relief(Gtk.ReliefStyle.NONE)
        plus.set_tooltip_text("New tape (Ctrl+T)")
        plus.connect("clicked", lambda *_: self.new_tape())
        plus.show()
        self.notebook.set_action_widget(plus, Gtk.PackType.END)
        vbox.pack_start(self.notebook, True, True, 0)

        vbox.pack_start(Gtk.Separator(), False, False, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        vbox.pack_start(bottom, False, False, 0)

        disp_row = Gtk.Box(spacing=6)
        self.count_label = Gtk.Label(xalign=0)
        self.count_label.get_style_context().add_class("dim-label")
        self.display = Gtk.Label(label="0.00", xalign=1)
        self.display.get_style_context().add_class("display")
        disp_row.pack_start(self.count_label, False, False, 0)
        disp_row.pack_end(self.display, True, True, 0)
        bottom.pack_start(disp_row, False, False, 0)

        input_row = Gtk.Box(spacing=6)
        self.amount = Gtk.Entry(placeholder_text="Amount", width_chars=12, xalign=1)
        self.amount.get_style_context().add_class("amount-entry")
        self.amount.connect("key-press-event", self._on_amount_key)
        self.amount.connect("activate", lambda *_: self.commit())
        self.amount.connect("changed", lambda *_: self._clear_error())
        self.amount.connect("paste-clipboard", self._on_entry_paste)
        self.note = Gtk.Entry(placeholder_text="Note (optional), then Tab")
        self.note.connect("activate", lambda *_: self.commit())
        self.note.connect("key-press-event", self._on_note_key)
        self.note.connect("paste-clipboard", self._on_entry_paste)
        input_row.pack_start(self.note, True, True, 0)
        input_row.pack_start(self.amount, False, False, 0)
        bottom.pack_start(input_row, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        bottom.pack_start(self.status, False, False, 0)

        self.keypad = self._build_keypad()
        self.keypad.set_no_show_all(True)
        bottom.pack_start(self.keypad, False, False, 0)
        vbox.show_all()

    def _build_tape_view(self, tape):
        tape.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        lb = tape.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.MULTIPLE,
                                        activate_on_single_click=False)
        lb.add_events(Gdk.EventMask.BUTTON1_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        lb.get_style_context().add_class("tape")
        lb.set_valign(Gtk.Align.FILL)
        hint = Gtk.Label(label="Type a note, press Tab, type the amount,\nthen press + or Enter.",
                         justify=Gtk.Justification.CENTER)
        hint.get_style_context().add_class("empty-hint")
        hint.show()
        lb.set_placeholder(hint)
        lb.connect("row-activated", lambda lb, row: self.edit_row(row.get_index()))
        lb.connect("button-press-event", self._on_list_button)
        lb.connect("motion-notify-event", self._on_list_drag)
        lb.connect("button-release-event", self._on_list_release)
        lb.connect("key-press-event", self._on_list_key)
        lb.connect("selected-rows-changed", self._on_selection_changed)
        tape.scroller.connect("scroll-event", self._on_tape_scroll)
        tape.scroller.add(lb)
        tape.scroller.tape = tape

        # Tab: the name (double-click to rename) and a close button.
        tab = Gtk.Box(spacing=4)
        name_box = Gtk.EventBox(visible_window=False)
        tape.tab_text = Gtk.Label(label=tape.name())
        name_box.add(tape.tab_text)
        name_box.set_tooltip_text("Double-click to rename")
        name_box.connect("button-press-event", lambda w, ev: (
            self.rename_tape(tape) if ev.type == Gdk.EventType.DOUBLE_BUTTON_PRESS else None) or False)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Close this tape (Ctrl+W)")
        close.connect("clicked", lambda *_: self.close_tape(tape))
        tab.pack_start(name_box, True, True, 0)
        tab.pack_start(close, False, False, 0)
        tab.show_all()
        tape.scroller.show_all()
        return tab

    def add_tape(self, tape, switch=True):
        tab = self._build_tape_view(tape)
        self.tapes.append(tape)
        if self.tape is None:
            self.tape = tape
        n = self.notebook.append_page(tape.scroller, tab)
        self.notebook.set_tab_reorderable(tape.scroller, True)
        if switch:
            self.notebook.set_current_page(n)
        return tape

    def _ordered_tapes(self):
        return [self.notebook.get_nth_page(i).tape for i in range(self.notebook.get_n_pages())]

    def _on_switch_page(self, nb, page, num):
        if self._move is not None:
            return
        self.tape = page.tape
        self._drag_anchor, self._dragging = None, False
        loading, self._loading = self._loading, True   # syncing the menu isn't a change
        self._set_decimals(self.tape.decimals)
        self._loading = loading
        self.refresh(scroll_to_end=True)
        self._save_state()

    def _next_title(self):
        used = {t.title for t in self.tapes}
        n = 1
        while f"Tape {n}" in used:
            n += 1
        return f"Tape {n}"

    def rename_tape(self, tape):
        d = Gtk.Dialog(title="Rename Tape", transient_for=self, modal=True)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Rename", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        name = Gtk.Entry(text=tape.name(), activates_default=True, width_chars=30, margin=12)
        d.get_content_area().add(name)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK and name.get_text().strip():
            tape.title = name.get_text().strip()
            tape.tab_text.set_text(tape.name())
            if tape is self.tape:
                self.refresh()
            self._save_state()
        d.destroy()

    def close_tape(self, tape):
        unsaved = tape.entries and (not tape.path or tape.dirty)
        if unsaved:
            n = len(tape.entries)
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.NONE, text=f"Close “{tape.name()}”?")
            d.format_secondary_text(f"Its {n} line{'s' if n != 1 else ''} aren't saved to a file, "
                                    "so they'll be gone." if not tape.path else
                                    "It has changes that aren't saved to its file.")
            d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Close Tape", Gtk.ResponseType.OK)
            answer = d.run()
            d.destroy()
            if answer != Gtk.ResponseType.OK:
                return
        self.notebook.remove_page(self.notebook.page_num(tape.scroller))
        self.tapes.remove(tape)
        try:
            os.remove(os.path.join(TAPES_DIR, tape.id + ".json"))
        except OSError:
            pass
        if not self.tapes:
            self.add_tape(Tape(title=self._next_title()))
        self._save_state()
        self.note.grab_focus()

    def set_zoom(self, step):
        """step +1 / -1 moves through ZOOM_STEPS, 0 resets to 100%."""
        if step == 0:
            z = 1.0
        else:
            i = min(range(len(ZOOM_STEPS)), key=lambda k: abs(ZOOM_STEPS[k] - self.zoom))
            z = ZOOM_STEPS[max(0, min(len(ZOOM_STEPS) - 1, i + step))]
        self.zoom = z
        self._apply_zoom()
        self.flash(f"Zoom {round(z * 100)}%")
        self._save_state()

    def _apply_zoom(self):
        z = self.zoom
        self.zoom_css.load_from_data((
            f".tape {{ font-size: {12 * z:.1f}pt; }}"
            f".tape .running, .tape .count {{ font-size: {9 * z:.1f}pt; }}"
            f".tape .work {{ font-size: {11 * z:.1f}pt; }}").encode())

    def _on_tape_scroll(self, scroller, event):
        """Ctrl + mouse wheel zooms the tape."""
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        ok, dx, dy = event.get_scroll_deltas()
        if ok and dy:
            self.set_zoom(-1 if dy > 0 else 1)
        elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            self.set_zoom(1 if event.direction == Gdk.ScrollDirection.UP else -1)
        return True

    def _build_keypad(self):
        grid = Gtk.Grid(row_spacing=5, column_spacing=5, column_homogeneous=True, row_homogeneous=True)
        grid.get_style_context().add_class("keypad")
        # (label, key, column, row, width, height, style class, tooltip)
        keys = [
            ("CE", "clear", 0, 0, 1, 1, "fn-key", "Clear the entry"),
            ("⌫", "back", 1, 0, 1, 1, "fn-key", "Backspace"),
            ("(", "(", 2, 0, 1, 1, "fn-key", "Brackets, e.g. (2+3)×4"),
            (")", ")", 3, 0, 1, 1, "fn-key", "Brackets, e.g. (2+3)×4"),
            ("÷", "÷", 4, 0, 1, 1, "op-key", "Divide"),
            ("7", "7", 0, 1, 1, 1, None, None), ("8", "8", 1, 1, 1, 1, None, None),
            ("9", "9", 2, 1, 1, 1, None, None),
            ("%", "%", 3, 1, 1, 1, "op-key", "Percent: 8% then + adds 8% of the running total; 200+8% is 216"),
            ("×", "×", 4, 1, 1, 1, "op-key", "Multiply"),
            ("4", "4", 0, 2, 1, 1, None, None), ("5", "5", 1, 2, 1, 1, None, None),
            ("6", "6", 2, 2, 1, 1, None, None),
            ("Σ", "Σ", 3, 2, 1, 1, "op-key", "The running total so far, e.g. Σ×8% or Σ÷2"),
            ("−", "-", 4, 2, 1, 1, "op-key", "Finish the line and subtract it from the tally"),
            ("1", "1", 0, 3, 1, 1, None, None), ("2", "2", 1, 3, 1, 1, None, None),
            ("3", "3", 2, 3, 1, 1, None, None),
            ("=", "=", 3, 3, 1, 1, "side-key", "Side calculation: show the answer without adding it"),
            ("+", "+", 4, 3, 1, 2, "plus-key", "Enter: finish the line and add it to the tally"),
            ("0", "0", 0, 4, 1, 1, None, None), ("00", "00", 1, 4, 1, 1, None, None),
            (".", ".", 2, 4, 1, 1, None, None),
            ("◇", "s", 3, 4, 1, 1, "fn-key", "Subtotal: print the total so far, keep counting"),
            ("✎ Note", "note", 0, 5, 2, 1, "fn-key", "Write a note for the next line (Tab)"),
            ("T  Total", "t", 2, 5, 3, 1, "suggested-action", "Total: print it and start a fresh tally"),
        ]
        # Keys whose symbol isn't self-explanatory get the word in small type under it.
        words = {"+": "Enter ⏎", "Σ": "Sum", "s": "Subtotal"}
        for label, key, c, r, w, h, cls, tip in keys:
            b = Gtk.Button(label=label, can_focus=False)
            if key in words:
                b.remove(b.get_child())
                stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
                word = Gtk.Label(label=words[key])
                word.get_style_context().add_class("key-word")
                stack.pack_start(Gtk.Label(label=label), False, False, 0)
                stack.pack_start(word, False, False, 0)
                stack.show_all()
                b.add(stack)
            if cls:
                b.get_style_context().add_class(cls)
            if tip:
                b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, k=key: self._keypad(k))
            b.show()
            grid.attach(b, c, r, w, h)
        return grid

    def _can_commit(self, text):
        """True when the amount box holds a finished line that + or − can put on the tape."""
        try:
            e = tc.parse_input(text, "", self.tape.total)
        except tc.ParseError:
            return False
        # Σ alone isn't finished: + after it starts "Σ + 10.5%" instead of adding the total to itself.
        return e is not None and e["kind"] == "num" and e["expr"] != "Σ"

    def _keypad(self, key):
        text = self.amount.get_text()
        if key in ("+", "-"):
            if self._can_commit(text):
                self.commit(op=key)
            else:
                self.amount.set_text(text + ("+" if key == "+" else "−"))
        elif key == "=":
            self.commit(side=True)
        elif key in ("t", "s"):
            if text.strip() and not self.commit():
                return
            self.commit(force=key)
        elif key == "clear":
            self.amount.set_text("")
        elif key == "back":
            self.amount.set_text(text[:-1])
        elif key == "note":
            self.note.grab_focus()
            return
        else:
            self.amount.set_text(text + key)
        self.amount.grab_focus_without_selecting()
        self.amount.set_position(-1)

    # ---------- rendering ----------
    def refresh(self, scroll_to_end=False, select=None):
        results = tc.compute(self.entries, self.decimals)
        self._sync_rows(results)
        total = tc.total_after(self.entries, results)
        self.tape.total = total
        self.display.set_text(tc.fmt(total, self.decimals))
        ctx = self.display.get_style_context()
        (ctx.add_class if total < 0 else ctx.remove_class)("neg")
        n = 0
        for e in reversed(self.entries):
            if e["kind"] == "total":
                break
            n += e["kind"] == "num"
        self.count_label.set_text(f"{n} line{'s' if n != 1 else ''} so far" if n else "")

        mark = "• " if self.dirty and self.path else ""
        self.tape.tab_text.set_text(mark + self.tape.name())
        self.set_title(mark + self.tape.name() + " — TallyForth")

        if select is not None and 0 <= select < len(self.entries):
            row = self.listbox.get_row_at_index(select)
            self.listbox.select_row(row)
        if scroll_to_end:
            GLib.idle_add(self._scroll_end)

    def _row_key(self, e, r):
        """Everything a row shows except its balance and Σ tooltip, which _sync_rows
        updates in place; rows with the same key can be kept as they are."""
        return (e["kind"], e.get("op"), e.get("expr"), e.get("note"), r["shown"], r["error"], r["count"],
                self.decimals)

    def _sync_rows(self, results):
        """Bring the tape's rows up to date, rebuilding only the ones that changed.
        Adding a line to a long tape then touches one row instead of all of them."""
        lb = self.listbox
        lb.unselect_all()
        old = lb.get_children()
        keys = [self._row_key(e, r) for e, r in zip(self.entries, results)]
        n = min(len(old), len(keys))
        head = 0
        while head < n and old[head].key == keys[head]:
            head += 1
        tail = 0
        while tail < n - head and old[-1 - tail].key == keys[-1 - tail]:
            tail += 1
        for row in old[head:len(old) - tail]:
            lb.remove(row)
        for i in range(head, len(keys) - tail):
            row = self._make_row(self.entries[i], results[i])
            row.key = keys[i]
            row.show_all()
            lb.insert(row, i)
        for row, r in zip(lb.get_children(), results):
            row.set_figures(r)

    def _scroll_end(self):
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _make_row(self, e, r):
        row = Gtk.ListBoxRow()
        row.set_figures = lambda r: None      # replaced below on rows that show a balance or Σ
        box = Gtk.Box(spacing=8)
        row.add(box)
        row.grip = Gtk.Label(label="⠿")
        row.grip.get_style_context().add_class("grip")
        row.grip.set_tooltip_text("Drag to move this line (Alt+↑ / Alt+↓ from the keyboard)")
        box.pack_start(row.grip, False, False, 0)
        k = e["kind"]
        note = Gtk.Label(label=e.get("note", ""), xalign=0)
        note.get_style_context().add_class("note")
        note.set_line_wrap(True)
        note.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(note, True, True, 0)
        if k == "note":
            note.set_selectable(False)
            return row

        right = Gtk.Box(spacing=6)
        box.pack_end(right, False, False, 0)
        side = k == "side"
        if k in ("num", "side"):
            if tc.is_calc(e["expr"]) or r["error"]:
                work = Gtk.Label(label=e["expr"] + " =", xalign=1)
                work.get_style_context().add_class("work")
                if "Σ" in e["expr"]:
                    row.work = work
                right.pack_start(work, False, False, 0)
            if r["error"]:
                err = Gtk.Label(label=f"⚠ {r['error']}")
                err.get_style_context().add_class("error")
                right.pack_start(err, False, False, 0)
                return row
            sym = "=" if side else tc.SIGN[e["op"]]
            negative = not side and (e["op"] == "-") != (r["shown"] < 0)
            if side:
                row.set_tooltip_text("Side calculation: shown here, not added to the tally")
        else:
            row.get_style_context().add_class("total-row" if k == "total" else "sub-row")
            if r["count"]:
                n = r["count"]
                cnt = Gtk.Label(label=f"{n} line{'s' if n != 1 else ''}")
                cnt.get_style_context().add_class("count")
                cnt.set_tooltip_text("How many + and − lines went into this total")
                right.pack_start(cnt, False, False, 0)
            sym = "T" if k == "total" else "◇"
            negative = r["shown"] < 0

        figure = tc.fmt(r["shown"], self.decimals)
        amt = Gtk.Label(label=figure, xalign=1, width_chars=10)
        amt.get_style_context().add_class("side-amt" if side else "amount")
        if negative:
            amt.get_style_context().add_class("neg")
        right.pack_start(amt, False, False, 0)
        op = Gtk.Label(label=sym, width_chars=1)
        op.get_style_context().add_class("op")
        if negative and k == "num":
            op.get_style_context().add_class("neg")
        right.pack_start(op, False, False, 0)
        # Balance column on the far right, like a ledger. Every figure row gets one
        # (blank where it doesn't apply) so the amounts line up.
        balance = Gtk.Label(xalign=1, width_chars=10)
        balance.get_style_context().add_class("running")
        if k == "num":
            balance.set_tooltip_text("Balance: the running total after this line")
        right.pack_start(balance, False, False, 0)
        work = getattr(row, "work", None)
        dec = self.decimals

        def set_figures(r):
            if k == "num":
                balance.set_text(tc.fmt(r["running"], dec))
            if work is not None:
                work.set_tooltip_text(f"Σ was {tc.fmt(r['sigma'], dec)} (the running total above this line)")
        row.set_figures = set_figures
        return row

    # ---------- editing ----------
    def _snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.entries))
        del self.undo_stack[:-200]
        self.redo_stack.clear()

    def _changed(self, **kw):
        self.dirty = True
        self._autosave()
        self.refresh(**kw)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.entries))
            self.entries = self.undo_stack.pop()
            self._changed()
            self.flash("Undone")

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.entries))
            self.entries = self.redo_stack.pop()
            self._changed()
            self.flash("Redone")

    def commit(self, op=None, force=None, side=False):
        """Put what's typed on the tape. op is the + or − key that finished the line;
        side=True makes it a side calculation. Returns True if a line was added."""
        amount_text = force if force else self.amount.get_text()
        note_text = self.note.get_text()
        if side:
            if not amount_text.strip():
                self.flash("Type a calculation first; = shows its answer without adding it")
                return False
            amount_text = "=" + amount_text.strip().lstrip("=")
        try:
            e = tc.parse_input(amount_text, note_text, self.tape.total)
        except tc.ParseError as ex:
            self.flash(f"Can't work out “{amount_text.strip()}”: {ex}", error=True)
            return False
        if e is None:
            return False
        if e["kind"] == "num" and e["expr"] == "Σ":
            self.flash("Σ alone would add the total to itself. For tax, type 10.5% then +; "
                       "to use the total in a sum, try Σ÷3 then =", error=True)
            return False
        if op and e["kind"] == "num":
            # "-15" then + adds −15; "-15" then − subtracts −15.
            e["op"] = "+" if e["op"] == op else "-"
        self._snapshot()
        self.entries.append(e)
        self.amount.set_text("")
        self.note.set_text("")
        # A line started with a note → back to the note box; a bare number → stay put
        # in the amount box for quick tallies.
        (self.note if note_text.strip() else self.amount).grab_focus()
        self._changed(scroll_to_end=True)
        return True

    def edit_row(self, i):
        if not (0 <= i < len(self.entries)):
            return
        e = self.entries[i]
        titles = {"num": "Edit Line", "side": "Edit Side Calculation", "note": "Edit Note",
                  "subtotal": "Subtotal Note", "total": "Total Note"}
        new = EditDialog(self, e, titles[e["kind"]]).result()
        if new is not None and new != e:
            self._snapshot()
            if new["kind"] == "note" and not new["note"]:
                del self.entries[i]
                self._changed()
            else:
                self.entries[i] = new
                self._changed(select=i)

    def insert_note_above(self, i):
        new = EditDialog(self, tc.entry("note"), "Add Note").result()
        if new and new["note"]:
            self._snapshot()
            self.entries.insert(i, new)
            self._changed(select=i)

    # ---------- pasting lists ----------
    def _clipboard_text(self):
        return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""

    def _on_entry_paste(self, entry):
        """Ctrl+V of several lines into a typing box puts them all on the tape."""
        text = self._clipboard_text()
        if "\n" in text.strip():
            entry.stop_emission_by_name("paste-clipboard")
            self.paste_lines(text)

    def paste_clipboard_list(self):
        text = self._clipboard_text()
        if not text.strip():
            self.flash("The clipboard is empty")
            return
        self.paste_lines(text)

    def paste_lines(self, text):
        new = tc.parse_pasted(text)
        if not new:
            self.flash("Nothing to paste")
            return
        chosen = self.selected_indices()
        at = chosen[-1] + 1 if chosen else len(self.entries)   # after the selection, else at the end
        self._snapshot()
        self.entries[at:at] = new
        self._changed(scroll_to_end=not chosen)
        for i in range(at, at + len(new)):
            self.listbox.select_row(self.listbox.get_row_at_index(i))
        nums = [e for e in new if e["kind"] == "num"]
        added = sum((tc.round_to(tc.evaluate(e["expr"]), self.decimals) * (1 if e["op"] == "+" else -1)
                     for e in nums), tc.Decimal(0))
        self.flash(f"Pasted {len(new)} line{'s' if len(new) != 1 else ''}"
                   + (f", {len(nums)} amounts adding up to {tc.fmt(added, self.decimals)}" if nums else "")
                   + " (Ctrl+Z to undo)")

    def set_kind(self, i, kind):
        self._snapshot()
        self.entries[i] = dict(self.entries[i], kind=kind, op="+")
        self._changed(select=i)

    def delete_rows(self, indices):
        indices = sorted({i for i in indices if 0 <= i < len(self.entries)})
        if not indices:
            self.flash("Click a line on the tape first")
            return
        list_had_focus = self.listbox.get_focus_child() is not None or self.listbox.has_focus()
        typing_in = self.get_focus() if self.get_focus() in (self.note, self.amount) else self.note
        self._snapshot()
        for i in reversed(indices):
            del self.entries[i]
        nxt = min(indices[0], len(self.entries) - 1)
        self._changed(select=nxt)
        # The rows were rebuilt, so put keyboard focus back where it was: on the newly
        # highlighted line if the tape had focus, so pressing Delete again keeps going.
        row = self.listbox.get_row_at_index(nxt) if nxt >= 0 else None
        if list_had_focus and row:
            row.grab_focus()
        else:
            typing_in.grab_focus_without_selecting()
        n = len(indices)
        self.flash(f"{n} line{'s' if n != 1 else ''} deleted (Ctrl+Z to undo)")

    # ---------- selection ----------
    def selected_indices(self):
        return sorted(r.get_index() for r in self.listbox.get_selected_rows())

    def listbox_select_all(self):
        self.listbox.select_all()
        first = self.listbox.get_row_at_index(0)
        if first:
            first.grab_focus()  # so Delete goes to the tape

    def _row_at(self, y):
        """The row under y, clamped to the first/last row when the pointer is above or below the tape."""
        n = len(self.entries)
        if not n:
            return None
        row = self.listbox.get_row_at_y(int(y))
        return row or self.listbox.get_row_at_index(0 if y < 0 else n - 1)

    def _on_list_button(self, lb, event):
        # The blank tape below the last line: click to deselect, double-click to select
        # everything, or drag up into the lines to select from the bottom line upward.
        if event.button == 1 and lb.get_row_at_y(int(event.y)) is None:
            self._drag_anchor, self._dragging = None, False
            if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
                self.listbox_select_all()
            elif event.type == Gdk.EventType.BUTTON_PRESS:
                lb.unselect_all()
                if self.entries:
                    self._drag_anchor, self._drag_from_blank = len(self.entries) - 1, True
            return True
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            row = lb.get_row_at_y(int(event.y))
            if row and self._on_grip(row, event.x):
                if not row.is_selected():
                    lb.unselect_all()
                    lb.select_row(row)
                self._move = {"lines": self.selected_indices(), "to": None}
                self._drag_anchor = None
                return True
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            plain = not (event.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK))
            row = lb.get_row_at_y(int(event.y))
            self._drag_anchor = row.get_index() if (row and plain) else None
            self._dragging = self._drag_from_blank = False
            return False
        if event.button != 3:
            return False
        row = lb.get_row_at_y(int(event.y))
        if row is None:
            return False
        if not row.is_selected():
            lb.unselect_all()
            lb.select_row(row)
        i = row.get_index()
        chosen = self.selected_indices()
        n = len(chosen)
        menu = Gtk.Menu()
        items = [("Edit…", lambda: self.edit_row(i)), ("Add Note Above…", lambda: self.insert_note_above(i))]
        kind = self.entries[i]["kind"]
        if kind == "side":
            items.append(("Add to Tally", lambda: self.set_kind(i, "num")))
        elif kind == "num":
            items.append(("Make Side Calculation", lambda: self.set_kind(i, "side")))
        items.append((f"Delete {n} Lines" if n > 1 else "Delete Line", lambda: self.delete_rows(chosen)))
        for label, cb in items:
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _m, f=cb: f())
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(lb, None)
        menu.popup_at_pointer(event)
        return True

    def _on_list_drag(self, lb, event):
        """Drag with the left button to select a run of lines (or move them, from a grip)."""
        held = event.state & Gdk.ModifierType.BUTTON1_MASK
        if self._move is not None and held:
            self._show_drop(event.y)
            self._autoscroll(event.y)
            return True
        if not held:
            row = lb.get_row_at_y(int(event.y))
            over = bool(row and self._on_grip(row, event.x))
            if over != self._grab_cursor:
                self._grab_cursor = over
                lb.get_window().set_cursor(
                    Gdk.Cursor.new_from_name(lb.get_display(), "grab") if over else None)
            return False
        if self._drag_anchor is None:
            return False
        row = self._row_at(event.y)
        if row is None:
            return False
        cur = row.get_index()
        if not self._dragging:
            # From a line: start once the pointer reaches another line.
            # From the blank tape: start as soon as the pointer is over any line.
            started = lb.get_row_at_y(int(event.y)) is not None if self._drag_from_blank \
                else cur != self._drag_anchor
            if not started:
                return False
        self._dragging = True
        lo, hi = sorted((self._drag_anchor, cur))
        if self.selected_indices() != list(range(lo, hi + 1)):
            lb.unselect_all()
            for i in range(lo, hi + 1):
                lb.select_row(lb.get_row_at_index(i))
        self._autoscroll(event.y)
        return False  # let GTK see the motion too, so releasing doesn't collapse the selection

    def _autoscroll(self, y):
        """Scroll the tape along when dragging past its top or bottom edge."""
        adj = self.scroller.get_vadjustment()
        if y < adj.get_value():
            adj.set_value(max(y, 0))
        elif y > adj.get_value() + adj.get_page_size():
            adj.set_value(min(y - adj.get_page_size(), adj.get_upper() - adj.get_page_size()))

    # ---------- moving lines ----------
    def _on_grip(self, row, x):
        g = row.grip.get_allocation()
        return x < g.x + g.width + 6

    def _show_drop(self, y):
        """Work out where dragged lines would land and draw a marker there."""
        row = self._row_at(y)
        if row is None:
            return
        a = row.get_allocation()
        i = row.get_index()
        to = i if y < a.y + a.height / 2 else i + 1
        self._move["to"] = to
        n = len(self.entries)
        mark = (self.listbox.get_row_at_index(to), "drop-before") if to < n else \
            (self.listbox.get_row_at_index(n - 1), "drop-after")
        if mark != self._marked:
            self._clear_drop()
            mark[0].get_style_context().add_class(mark[1])
            self._marked = mark

    def _clear_drop(self):
        if self._marked:
            self._marked[0].get_style_context().remove_class(self._marked[1])
            self._marked = None

    def move_lines(self, lines, to):
        new, moved = tc.move_lines(self.entries, lines, to)
        if new == self.entries:
            return
        self._snapshot()
        self.entries = new
        self._changed()
        for i in moved:
            self.listbox.select_row(self.listbox.get_row_at_index(i))
        self.listbox.get_row_at_index(moved[0]).grab_focus()
        self.flash(f"Moved {len(moved)} line{'s' if len(moved) != 1 else ''} (Ctrl+Z to undo)")

    def move_selected(self, step):
        lines = self.selected_indices()
        if not lines:
            self.flash("Click a line on the tape first")
            return
        if step < 0 and lines[0] > 0:
            self.move_lines(lines, lines[0] - 1)
        elif step > 0 and lines[-1] < len(self.entries) - 1:
            self.move_lines(lines, lines[-1] + 2)

    def _on_list_release(self, lb, event):
        if event.button == 1 and self._move is not None:
            move, self._move = self._move, None
            self._clear_drop()
            if move["to"] is not None:
                self.move_lines(move["lines"], move["to"])
            return True
        if event.button == 1:
            if self._dragging:
                # GTK's own release handling re-selects just the row the press started on,
                # so put the dragged range back once it has run.
                GLib.timeout_add(0, self._restore_selection, self.selected_indices())
            self._drag_anchor, self._dragging = None, False
        return False

    def _restore_selection(self, indices):
        self.listbox.unselect_all()
        for i in indices:
            row = self.listbox.get_row_at_index(i)
            if row:
                self.listbox.select_row(row)
        self.listbox.grab_focus()
        return False

    def _on_selection_changed(self, lb):
        n = len(lb.get_selected_rows())
        if n > 1:
            self.status.set_text(f"{n} lines selected · Delete removes them · Esc to deselect")
            self._selection_hint = True
        elif getattr(self, "_selection_hint", False):
            self.status.set_text("")
            self._selection_hint = False

    def _on_list_key(self, lb, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK and Gdk.keyval_to_lower(event.keyval) == Gdk.KEY_v:
            self.paste_clipboard_list()
            return True
        chosen = self.selected_indices()
        if chosen and event.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.delete_rows(chosen)
            return True
        if event.keyval == Gdk.KEY_Escape:
            lb.unselect_all()
            self.note.grab_focus()
            return True
        return False

    # ---------- keyboard ----------
    OP_KEYS = {Gdk.KEY_plus: "+", Gdk.KEY_KP_Add: "+", Gdk.KEY_minus: "-", Gdk.KEY_KP_Subtract: "-"}
    PRETTY_KEYS = {Gdk.KEY_asterisk: "×", Gdk.KEY_KP_Multiply: "×", Gdk.KEY_slash: "÷", Gdk.KEY_KP_Divide: "÷"}

    def _on_amount_key(self, entry, event):
        text = entry.get_text()
        kv = event.keyval
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        pos = entry.get_position()
        if kv in self.OP_KEYS and pos == len(text) and self._can_commit(text):
            self.commit(op=self.OP_KEYS[kv])
            return True
        # Show * and / as × and ÷ while typing a calculation.
        before = text[:pos].rstrip()
        if kv in self.PRETTY_KEYS and before and (before[-1].isdigit() or before[-1] in ")%Σ"):
            entry.delete_selection()
            pos = entry.get_position()
            entry.insert_text(self.PRETTY_KEYS[kv], pos)
            entry.set_position(pos + 1)
            return True
        if self._tape_keys(entry, event):
            return True
        if kv in (Gdk.KEY_equal, Gdk.KEY_KP_Equal):
            self.commit(side=True)
            return True
        if kv == Gdk.KEY_KP_Enter:
            self.commit()
            return True
        return False

    def _on_note_key(self, entry, event):
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        if self._tape_keys(entry, event):
            return True
        # Typed just a number or a calculation into the note box? Treat it as the amount
        # once an operator or Enter shows that's what it was.
        text = entry.get_text()
        kv = event.keyval
        ends_line = kv in self.OP_KEYS or kv in self.PRETTY_KEYS or kv in (
            Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_equal, Gdk.KEY_KP_Equal, Gdk.KEY_percent)
        if ends_line and entry.get_position() == len(text) and not self.amount.get_text().strip():
            toks, rest = tc.tokenize(text)
            if text.strip() and toks and not rest:
                self.amount.set_text(text.strip())
                entry.set_text("")
                self.amount.grab_focus_without_selecting()
                self.amount.set_position(-1)
                if kv == Gdk.KEY_percent:
                    self.amount.insert_text("%", self.amount.get_position())
                    self.amount.set_position(-1)
                    return True
                if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                    self.commit()
                    return True
                return self._on_amount_key(self.amount, event)
        return False

    def _tape_keys(self, entry, event):
        """Keys that act on the tape from either typing box."""
        kv = event.keyval
        text = entry.get_text()
        # Delete with the cursor at the end of a box has nothing to erase,
        # so it removes the highlighted tape lines instead.
        if kv in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and entry.get_position() == len(text) \
                and not entry.get_selection_bounds():
            chosen = self.selected_indices()
            if chosen:
                self.delete_rows(chosen)
            elif not text:
                self.flash("Highlight a line first: click it, or press ↑ to step up the tape")
            return bool(chosen) or not text
        if kv == Gdk.KEY_Up and self.entries:
            last = self.listbox.get_row_at_index(len(self.entries) - 1)
            self.listbox.unselect_all()
            self.listbox.select_row(last)
            last.grab_focus()
            return True
        if kv == Gdk.KEY_Escape:
            self.amount.set_text("")
            self.note.set_text("")
            self.note.grab_focus()
            return True
        return False

    # ---------- status ----------
    def flash(self, msg, error=False):
        self.status.set_markup(f"<span foreground='#b3261e'>{GLib.markup_escape_text(msg)}</span>"
                               if error else GLib.markup_escape_text(msg))
        if getattr(self, "_flash_id", None):
            GLib.source_remove(self._flash_id)
        self._flash_id = GLib.timeout_add_seconds(4, self._clear_error)

    def _clear_error(self):
        self.status.set_text("")
        self._flash_id = None
        return False

    def _on_decimals(self, mi):
        if mi.get_active() and self.decimals != mi.decimals_value:
            self.decimals = mi.decimals_value
            self._autosave()
            self.refresh()

    def show_about(self):
        d = Gtk.AboutDialog(transient_for=self, modal=True, program_name="TallyForth",
                            logo_icon_name=self.get_application().icon_name,
                            version=VERSION, website=WEBSITE, copyright="© 2026 Ryan Howell",
                            license_type=Gtk.License.GPL_3_0,
                            comments="An adding-machine calculator with notes alongside the numbers.")
        d.run()
        d.destroy()

    def show_help(self):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.CLOSE, text="TallyForth")
        d.format_secondary_markup(HELP)
        d.run()
        d.destroy()

    # ---------- files ----------
    def _file_dialog(self, action, title):
        btn = "Open" if action == Gtk.FileChooserAction.OPEN else "Save"
        d = Gtk.FileChooserNative(title=title, transient_for=self, action=action, accept_label=btn)
        if action == Gtk.FileChooserAction.SAVE:
            d.set_do_overwrite_confirmation(True)
        return d

    def _tape_filter(self, d):
        f = Gtk.FileFilter()
        f.set_name("TallyForth tapes (*.tally)")
        f.add_pattern("*.tally")
        f.add_pattern("*.tape")  # saved before the rename
        d.add_filter(f)
        a = Gtk.FileFilter()
        a.set_name("All files")
        a.add_pattern("*")
        d.add_filter(a)

    def new_tape(self):
        self.add_tape(Tape(decimals=self.decimals, title=self._next_title()))
        self._autosave()
        self.note.grab_focus()

    def open_tape(self):
        d = self._file_dialog(Gtk.FileChooserAction.OPEN, "Open Tape")
        self._tape_filter(d)
        if d.run() == Gtk.ResponseType.ACCEPT:
            self._open_path(d.get_filename())
        d.destroy()

    def _open_path(self, path):
        for t in self.tapes:
            if t.path and os.path.abspath(t.path) == os.path.abspath(path):
                self.notebook.set_current_page(self.notebook.page_num(t.scroller))
                self.flash(f"{os.path.basename(path)} is already open")
                return
        try:
            with open(path) as f:
                entries, dec = tc.loads(f.read())
        except (OSError, ValueError) as ex:
            self.flash(f"Couldn't open {os.path.basename(path)}: {ex}", error=True)
            return
        t = self.tape
        if t.entries or t.path or t.undo_stack:     # keep the current tab; open alongside it
            t = self.add_tape(Tape())
        t.entries, t.decimals, t.path, t.dirty, t.title = entries, dec, path, False, None
        self._set_decimals(dec)
        self._autosave()
        self.refresh(scroll_to_end=True)

    def save_tape(self):
        if not self.path:
            return self.save_as()
        try:
            # Write a temporary file and swap it in, so a crash mid-save can't leave half a file.
            with open(self.path + ".tmp", "w") as f:
                f.write(tc.dumps(self.entries, self.decimals))
            os.replace(self.path + ".tmp", self.path)
        except OSError as ex:
            self.flash(f"Couldn't save to {self.path}: {ex.strerror}. Choose where to save it.", error=True)
            self.save_as()
            return
        self.dirty = False
        self._autosave()
        self.refresh()
        self.flash(f"Saved {os.path.basename(self.path)}")

    def save_as(self):
        d = self._file_dialog(Gtk.FileChooserAction.SAVE, "Save Tape")
        self._tape_filter(d)
        d.set_current_name(os.path.basename(self.path) if self.path else "tape.tally")
        if d.run() == Gtk.ResponseType.ACCEPT:
            path = d.get_filename()
            if not os.path.splitext(path)[1]:
                path += ".tally"
            self.path = path
            if self.tape.title and self.tape.title.startswith("Tape "):
                self.tape.title = None          # name the tab after the file
            self.save_tape()
        d.destroy()

    def export_text(self):
        d = self._file_dialog(Gtk.FileChooserAction.SAVE, "Export Tape as Text")
        base = os.path.splitext(os.path.basename(self.path))[0] if self.path else "tape"
        d.set_current_name(base + ".txt")
        if d.run() == Gtk.ResponseType.ACCEPT:
            try:
                with open(d.get_filename(), "w") as f:
                    f.write(tc.to_text(self.entries, self.decimals))
                self.flash(f"Exported {os.path.basename(d.get_filename())}")
            except OSError as ex:
                self.flash(f"Couldn't export: {ex}", error=True)
        d.destroy()

    def export_csv(self):
        d = self._file_dialog(Gtk.FileChooserAction.SAVE, "Export Tape as CSV")
        d.set_current_name(self.tape.name() + ".csv")
        if d.run() == Gtk.ResponseType.ACCEPT:
            path = d.get_filename()
            if not os.path.splitext(path)[1]:
                path += ".csv"
            try:
                # utf-8-sig so spreadsheet apps read Σ and × correctly
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    f.write(tc.to_csv(self.entries, self.decimals))
                self.flash(f"Exported {os.path.basename(path)}")
            except OSError as ex:
                self.flash(f"Couldn't export: {ex}", error=True)
        d.destroy()

    def copy_text(self):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(tc.to_text(self.entries, self.decimals), -1)
        self.flash("Tape copied to clipboard")

    # ---------- persistence ----------
    def _set_decimals(self, dec):
        self.decimals = dec
        for mi in self.decimal_items:
            if mi.decimals_value == dec:
                mi.set_active(True)

    def _autosave(self):
        """Save the front tape and the list of tabs."""
        if self._loading or self.tape is None:
            return
        try:
            os.makedirs(TAPES_DIR, exist_ok=True)
            self._write_tape(self.tape)
        except OSError as ex:
            self.flash(f"Autosave failed: {ex}", error=True)
        self._save_state()

    def _write_tape(self, tape):
        dest = os.path.join(TAPES_DIR, tape.id + ".json")
        with open(dest + ".tmp", "w") as f:
            f.write(tc.dumps(tape.entries, tape.decimals))
        os.replace(dest + ".tmp", dest)

    def _save_state(self):
        if self._loading or self.tape is None:
            return
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tapes = self._ordered_tapes()
            with open(STATE + ".tmp", "w") as f:
                json.dump({"tapes": [{"id": t.id, "title": t.title, "path": t.path, "dirty": t.dirty} for t in tapes],
                           "active": tapes.index(self.tape) if self.tape in tapes else 0,
                           "keypad": self.keypad_item.get_active(), "zoom": self.zoom}, f)
            os.replace(STATE + ".tmp", STATE)
        except OSError as ex:
            self.flash(f"Autosave failed: {ex}", error=True)

    def _load_state(self):
        for old in OLD_DATA_DIRS:
            fresh = not os.path.isdir(DATA_DIR) or not os.listdir(DATA_DIR)  # missing, or an empty folder
            if fresh and old != DATA_DIR and os.path.isdir(old):
                try:
                    shutil.copytree(old, DATA_DIR, dirs_exist_ok=True)
                except OSError:
                    pass
                if old == HOST_DATA_DIR:
                    self._forget_file_links()
        self.keypad_item.set_active(True)
        try:
            with open(STATE) as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        self.keypad_item.set_active(bool(st.get("keypad", True)))
        z = st.get("zoom", 1.0)
        self.zoom = z if isinstance(z, (int, float)) and 0.5 <= z <= 3 else 1.0
        self._apply_zoom()

        tapes = []
        for info in st.get("tapes", []):
            try:
                with open(os.path.join(TAPES_DIR, info["id"] + ".json")) as f:
                    entries, dec = tc.loads(f.read())
            except (OSError, ValueError, KeyError, TypeError):
                continue
            tapes.append(Tape(entries, dec, info.get("path"), bool(info.get("dirty")),
                              info.get("title"), info["id"]))
        if not tapes and "tapes" not in st:
            # From before tabs: one autosave.json plus its path in state.json.
            try:
                with open(AUTOSAVE) as f:
                    entries, dec = tc.loads(f.read())
                tapes.append(Tape(entries, dec, st.get("path"), bool(st.get("dirty")),
                                  None if st.get("path") else "Tape 1"))
            except (OSError, ValueError):
                pass
        for t in tapes or [Tape(title="Tape 1")]:
            self.add_tape(t, switch=False)
        active = st.get("active", 0)
        self.notebook.set_current_page(active if isinstance(active, int) and 0 <= active < len(self.tapes) else 0)
        self._set_decimals(self.tape.decimals)
        self._first_run_save = not tapes or "tapes" not in st

    def _forget_file_links(self):
        """Tapes copied in from outside the Flatpak sandbox keep their lines, but the
        files they were saved to can't be reached from inside it. Unlink them (the tab
        keeps the file's name) so Save asks where to save instead of failing."""
        try:
            with open(STATE) as f:
                st = json.load(f)
            for info in st.get("tapes", []):
                if info.get("path"):
                    info["title"] = info.get("title") or os.path.splitext(os.path.basename(info["path"]))[0]
                    info["path"], info["dirty"] = None, False
            st.pop("path", None)                  # the single tape from before tabs
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f)
            os.replace(STATE + ".tmp", STATE)
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def _on_close(self, *_):
        try:
            os.makedirs(TAPES_DIR, exist_ok=True)
            for t in self.tapes:
                self._write_tape(t)
        except OSError:
            pass
        self._save_state()
        return False


class TallyForthApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        GLib.set_application_name("TallyForth")
        GLib.set_prgname(APP_ID)  # so the window matches its menu entry and icon
        theme = Gtk.IconTheme.get_default()
        self.icon_name = APP_ID if theme.has_icon(APP_ID) else "accessories-calculator"
        Gtk.Window.set_default_icon_name(self.icon_name)

    def do_activate(self):
        win = self.get_active_window() or TapeWindow(self)
        win.present()


if __name__ == "__main__":
    sys.exit(TallyForthApp().run(sys.argv))
