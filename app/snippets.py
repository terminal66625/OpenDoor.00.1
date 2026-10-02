# -*- coding: utf-8 -*-
"""代码片段收藏：保存对话里的代码块，支持标签与关键词搜索、双击复制。"""
from __future__ import annotations

import datetime
import os
import re
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QTextEdit,
                             QVBoxLayout, QWidget)

from . import const
from . import ui_theme
from .logging_setup import setup_logging
from .util import atomic_write_json, read_json

log = setup_logging()

SNIPPET_PATH = os.path.join(const.MEMORY_DIR, "snippets.json")

CODE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.S)


def extract_code_blocks(text: str) -> List[Dict[str, str]]:
    out = []
    for m in CODE_RE.finditer(text or ""):
        out.append({"lang": (m.group(1) or "").strip(), "code": m.group(2).rstrip()})
    return out


class SnippetStore:
    def __init__(self) -> None:
        self.items: List[Dict] = read_json(SNIPPET_PATH, []) or []

    def save(self) -> None:
        atomic_write_json(SNIPPET_PATH, self.items)

    def add(self, code: str, tags: str = "", title: str = "", lang: str = "") -> Dict:
        code = (code or "").strip()
        item = {
            "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "title": (title or code.splitlines()[0] if code else "代码")[:40],
            "code": code, "lang": lang,
            "tags": [t.strip() for t in (tags or "").split() if t.strip()],
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self.items.insert(0, item)
        self.save()
        return item

    def remove(self, item_id: str) -> None:
        self.items = [i for i in self.items if i.get("id") != item_id]
        self.save()

    def search(self, keyword: str) -> List[Dict]:
        kw = (keyword or "").strip().lower()
        if not kw:
            return list(self.items)
        out = []
        for it in self.items:
            hay = " ".join([it.get("title", ""), it.get("code", ""),
                            it.get("lang", ""), " ".join(it.get("tags") or [])]).lower()
            if kw in hay:
                out.append(it)
        return out


class SnippetsDialog(QDialog):
    def __init__(self, store: SnippetStore, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.store = store
        self.setWindowTitle("大肥鱼 · 代码收藏夹")
        self.setStyleSheet(ui_theme.DIALOG_QSS)
        self.resize(780, 480)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)
        head = QLabel(ui_theme.header("代码收藏夹",
                                      "哼，本鱼帮你存着代码，可别弄丢了哦~"))
        head.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(head)
        root = QHBoxLayout()
        outer.addLayout(root, 1)

        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索关键词 / 标签 / 语言…")
        self.search.textChanged.connect(self._refresh)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show_code)
        self.list.itemDoubleClicked.connect(self._copy_selected)
        left.addWidget(self.list, 1)
        btn_row = QHBoxLayout()
        b_copy = QPushButton("复制（双击）")
        b_copy.clicked.connect(self._copy_selected)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._delete)
        btn_row.addWidget(b_copy); btn_row.addWidget(b_del)
        left.addLayout(btn_row)
        root.addLayout(left, 2)

        right = QVBoxLayout()
        right.addWidget(QLabel("代码内容："))
        self.code = QTextEdit()
        self.code.setReadOnly(True)
        right.addWidget(self.code, 1)
        self.meta = QLabel("")
        self.meta.setStyleSheet("color:#7a93ad;font-size:12px;")
        right.addWidget(self.meta)
        root.addLayout(right, 3)

        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        for it in self.store.search(self.search.text()):
            tags = ("　#" + " #".join(it.get("tags") or [])) if it.get("tags") else ""
            item = QListWidgetItem(f"{it.get('title', '')}{tags}")
            item.setData(Qt.ItemDataRole.UserRole, it)
            self.list.addItem(item)

    def _current(self) -> Optional[Dict]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_code(self) -> None:
        it = self._current()
        if not it:
            self.code.clear(); self.meta.clear(); return
        self.code.setPlainText(it.get("code", ""))
        self.meta.setText(f"语言：{it.get('lang') or '未知'}　标签：{'、'.join(it.get('tags') or []) or '无'}　"
                          f"收藏于 {it.get('ts', '')}")

    def _copy_selected(self) -> None:
        it = self._current()
        if not it:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(it.get("code", ""))
        self.meta.setText("已复制到剪贴板 ✔")

    def _delete(self) -> None:
        it = self._current()
        if not it:
            return
        if QMessageBox.question(self, "删除", "删除这条收藏？") == QMessageBox.StandardButton.Yes:
            self.store.remove(it.get("id", ""))
            self._refresh()


def prompt_and_add(store: SnippetStore, code: str, lang: str = "", parent=None) -> bool:
    if not code.strip():
        return False
    tags, ok = QInputDialog.getText(parent, "收藏代码", "给它加分类标签（空格分隔）：",
                                    QLineEdit.EchoMode.Normal, "")
    if not ok:
        return False
    store.add(code, tags=tags, lang=lang)
    return True
