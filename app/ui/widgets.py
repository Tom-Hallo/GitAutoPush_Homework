"""
ui/widgets.py
Small reusable widgets used by the repository table:

- ElidedLabel        : QLabel that elides long text (middle "...") and
                        always shows the full value as a tooltip, and
                        re-elides itself whenever the column is resized.
- StatusBadge         : colored "chip" label for Not-UP / Pushing /
                        Success / Failed.
- MultiCursorTextEdit : single-line-feeling text editor that supports a
                        VS Code-like Ctrl+D "select next occurrence,
                        then type to replace all of them at once".
- DroppableRepoTable  : QTableWidget that accepts one or more folders
                        dragged in from Windows Explorer and emits
                        foldersDropped(list[str]) in drop order.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import QLabel, QTextEdit, QTableWidget, QSizePolicy

# ---------------------------------------------------------------- Status UI

STATUS_NOT_UP = "Not-UP"
STATUS_PUSHING = "Pushing"
STATUS_SUCCESS = "Success"
STATUS_FAILED = "Failed"

# (background, foreground) per status -- used for the table's status chip.
STATUS_BADGE_COLORS = {
    STATUS_NOT_UP: ("#fff3cd", "#8a6100"),   # yellow
    STATUS_PUSHING: ("#e3f2fd", "#0a66c2"),  # blue (transitional)
    STATUS_SUCCESS: ("#e6f4ea", "#1a7f37"),  # green
    STATUS_FAILED: ("#fde2e1", "#c62828"),   # red
}


class StatusBadge(QLabel):
    """Small rounded 'chip' label showing the repository push status."""

    def __init__(self, status: str = STATUS_NOT_UP, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str):
        text = "Pushing..." if status == STATUS_PUSHING else status
        self.setText(text)
        bg, fg = STATUS_BADGE_COLORS.get(status, ("#eeeeee", "#555555"))
        self.setStyleSheet(
            f"QLabel {{ background-color:{bg}; color:{fg}; border-radius:9px; "
            f"padding:3px 10px; font-weight:600; }}"
        )


# ---------------------------------------------------------------- ElidedLabel

class ElidedLabel(QLabel):
    """QLabel that keeps the full text as a tooltip and elides
    (middle-truncates) the displayed text to whatever width the cell
    currently has, so long folder paths / repo names never overflow the
    table or overlap neighbouring widgets -- including after the user
    resizes or maximizes the window."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.set_full_text(text)

    def set_full_text(self, text: str):
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._reelide()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reelide()

    def _reelide(self):
        fm = self.fontMetrics()
        width = max(self.width(), 24)
        elided = fm.elidedText(self._full_text, Qt.ElideMiddle, width)
        QLabel.setText(self, elided)


# ---------------------------------------------------------- Multi-cursor edit

class MultiCursorTextEdit(QTextEdit):
    """A single-line text editor with a simplified, VS Code-style
    Ctrl+D "select next occurrence" / multi-edit behaviour:

        Ctrl+D            -> select the word under the cursor
        Ctrl+D again      -> also select the next occurrence of that text
        Ctrl+D again      -> select the next occurrence after that, etc.
        (type something)  -> every selected occurrence is replaced at once

    Real multi-caret editing needs multiple independent text cursors,
    which QTextEdit/QLineEdit do not natively support. This widget
    approximates the same end result: it tracks the selected occurrence
    ranges itself and re-applies every keystroke to all of them in one
    atomic edit (grouped for a single Ctrl+Z), while leaving normal
    typing, Ctrl+C / Ctrl+V / Ctrl+Z, Tab/Shift+Tab focus traversal, and
    Enter-to-confirm behaving exactly like a normal single-line field.
    """

    editingFinished = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setTabChangesFocus(True)          # Tab / Shift+Tab move focus, don't insert a tab
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        fm = self.fontMetrics()
        self.setFixedHeight(fm.height() + 14)
        self._ranges: list[tuple[int, int]] = []  # multi-selected occurrence ranges
        if text:
            self.setPlainText(text)

    # -- QLineEdit-compatible convenience API (used by main_window.py) --

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str):
        self._ranges = []
        self.setPlainText(text or "")

    # ------------------------------------------------------------- events

    def focusOutEvent(self, event):
        self._clear_multiselect()
        super().focusOutEvent(event)
        self.editingFinished.emit()

    def mousePressEvent(self, event):
        self._clear_multiselect()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)

        # Enter/Return confirms the edit instead of inserting a newline --
        # a commit message field must never gain a hidden line break, and
        # Enter must never be mistaken for a dangerous action elsewhere.
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._clear_multiselect()
            event.accept()
            self.clearFocus()
            self.editingFinished.emit()
            return

        if key == Qt.Key_Escape:
            self._clear_multiselect()
            event.accept()
            return

        if ctrl and key == Qt.Key_D:
            self._select_next_occurrence()
            event.accept()
            return

        # While several occurrences are selected, typed characters /
        # Backspace / Delete are applied to all of them at once.
        if self._ranges and self._is_plain_edit_key(event):
            self._apply_multi_edit(event)
            event.accept()
            return

        # Any other navigation/editing key drops back to a single cursor
        # (matches the common editor convention: arrow keys, hom/end,
        # etc. collapse a multi-selection rather than doing something
        # undefined with it).
        if self._ranges and key in (
            Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
            Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown,
        ):
            self._clear_multiselect()

        super().keyPressEvent(event)

    # --------------------------------------------------------- Ctrl+D logic

    def _is_plain_edit_key(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            return True
        text = event.text()
        if not text:
            return False
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            return False
        return text.isprintable()

    def _current_selection_range(self) -> tuple[int, int] | None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return None
        return (cursor.selectionStart(), cursor.selectionEnd())

    def _select_next_occurrence(self):
        doc_text = self.toPlainText()

        if not self._ranges:
            sel = self._current_selection_range()
            if sel is None:
                # Nothing selected yet -- select the word under the cursor.
                cursor = self.textCursor()
                cursor.select(QTextCursor.WordUnderCursor)
                if not cursor.hasSelection():
                    return
                sel = (cursor.selectionStart(), cursor.selectionEnd())
            self._ranges = [sel]
            self._paint_ranges()
            self._move_caret_to(self._ranges[-1])
            return

        start0, end0 = self._ranges[0]
        needle = doc_text[start0:end0]
        if not needle:
            return

        search_from = max(end for _, end in self._ranges)
        idx = doc_text.find(needle, search_from)
        if idx == -1:
            idx = doc_text.find(needle)  # wrap around
        if idx == -1:
            return

        new_range = (idx, idx + len(needle))
        if new_range in self._ranges:
            return  # already selected every occurrence
        self._ranges.append(new_range)
        self._paint_ranges()
        self._move_caret_to(new_range)

    def _move_caret_to(self, rng: tuple[int, int]):
        cursor = self.textCursor()
        cursor.setPosition(rng[0])
        cursor.setPosition(rng[1], QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)

    def _paint_ranges(self):
        selections = []
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffd54f"))
        for start, end in self._ranges:
            cursor = self.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)

    def _apply_multi_edit(self, event):
        key = event.key()
        doc_len = len(self.toPlainText())

        # First work out what each range's edit actually is. A typed
        # character always replaces whatever is currently selected at
        # that occurrence (which, after the first keystroke, is a
        # collapsed (empty) range sitting right where typing should
        # continue -- so "replace" degrades naturally into "insert").
        # Backspace/Delete on a collapsed range behave like a normal
        # single-cursor Backspace/Delete (remove one character before/
        # after the caret) instead of a no-op on an empty selection.
        edits: list[tuple[int, int, str]] = []  # (edit_start, edit_end, text)
        for start, end in self._ranges:
            if key == Qt.Key_Backspace:
                if start != end:
                    edits.append((start, end, ""))
                else:
                    edits.append((max(0, start - 1), start, ""))
            elif key == Qt.Key_Delete:
                if start != end:
                    edits.append((start, end, ""))
                else:
                    edits.append((start, min(doc_len, start + 1), ""))
            else:
                edits.append((start, end, event.text()))

        edits_sorted = sorted(edits, key=lambda r: r[0])
        doc_cursor = self.textCursor()
        doc_cursor.beginEditBlock()
        offset = 0
        new_ranges: list[tuple[int, int]] = []
        for edit_start, edit_end, text in edits_sorted:
            s, e = edit_start + offset, edit_end + offset
            cursor = self.textCursor()
            cursor.setPosition(s)
            cursor.setPosition(e, QTextCursor.KeepAnchor)
            cursor.insertText(text)
            new_pos = s + len(text)
            # Collapsed range: the caret sits right after the edit, ready
            # for the *next* keystroke to be appended rather than to
            # replace the text we just typed.
            new_ranges.append((new_pos, new_pos))
            offset += len(text) - (edit_end - edit_start)
        doc_cursor.endEditBlock()

        self._ranges = new_ranges
        self._paint_ranges()
        if new_ranges:
            self._move_caret_to(new_ranges[-1])

    def _clear_multiselect(self):
        if self._ranges:
            self._ranges = []
            self.setExtraSelections([])


# --------------------------------------------------------------- Drag & drop

class DroppableRepoTable(QTableWidget):
    """QTableWidget that accepts one or more folders dragged in from the
    OS file manager and reports them, in drop order, via
    foldersDropped(list[str])."""

    foldersDropped = Signal(list)

    def __init__(self, rows: int, cols: int, parent=None):
        super().__init__(rows, cols, parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        folders = []
        for url in urls:
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isdir(path):
                folders.append(path)
        event.acceptProposedAction()
        if folders:
            self.foldersDropped.emit(folders)
