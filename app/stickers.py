# -*- coding: utf-8 -*-
"""表情包匹配：根据关键词/情绪从本地素材库挑选合适图片。"""
import os
import random
from typing import Dict, List, Optional

from . import const
from .assets import EMOTION_SYNONYMS
from .logging_setup import setup_logging
from .util import atomic_write_json, read_json

log = setup_logging()

RECENT_LIMIT = 10   # 最近用过的表情包不去重


class StickerLibrary:
    def __init__(self) -> None:
        self.items: List[Dict] = read_json(const.STICKER_INDEX_PATH, []) or []
        self._fix_paths()
        self._by_name: Dict[str, List[Dict]] = {}
        for it in self.items:
            self._by_name.setdefault(it["name"], []).append(it)
        # 最近用过的表情包名（最多 RECENT_LIMIT 个，跨重启保留）
        self._recent: List[str] = read_json(const.STICKER_RECENT_PATH, []) or []

    def _fix_paths(self) -> None:
        """索引里的旧路径不存在时，尝试程序目录内自带的素材（整个文件夹搬走也能用）。"""
        for it in self.items:
            p = it.get("path", "")
            if p and os.path.exists(p):
                continue
            fn = it.get("file") or os.path.basename(p or "")
            if not fn:
                continue
            for base in (os.path.join(const.BASE_DIR, "大肥鱼印象", "表情包"),
                         os.path.join(const.BASE_DIR, "表情包")):
                cand = os.path.join(base, fn)
                if os.path.exists(cand):
                    it["path"] = cand
                    break

    def all(self) -> List[Dict]:
        return self.items

    def path_of(self, item: Dict) -> str:
        return item.get("path", "")

    def _eligible(self) -> List[Dict]:
        """排除最近用过的，避免与前 10 次重复；若都被排除则放宽。"""
        recent = set(self._recent)
        pool = [it for it in self.items if it["name"] not in recent]
        return pool or self.items

    def _record(self, name: str) -> None:
        self._recent.append(name)
        self._recent = self._recent[-RECENT_LIMIT:]
        atomic_write_json(const.STICKER_RECENT_PATH, self._recent)

    def random_path(self) -> Optional[str]:
        pool = self._eligible()
        if not pool:
            return None
        chosen = random.choice(pool)
        self._record(chosen["name"])
        return chosen["path"]

    def pick(self, keyword: Optional[str], context: str = "") -> Optional[str]:
        """按关键词匹配；找不到就用语境文字模糊匹配；再不行返回 None。
        自动避免与最近 10 次发送的表情包重名。"""
        if not self.items:
            return None
        keys: List[str] = []
        if keyword:
            keyword = keyword.strip()
            keys.append(keyword)
            for emotion, words in EMOTION_SYNONYMS.items():
                if keyword in emotion or any(w in keyword for w in words):
                    keys.append(emotion)
                    keys.extend(words)
        if context:
            for emotion, words in EMOTION_SYNONYMS.items():
                if emotion in context or any(w in context for w in words):
                    keys.append(emotion)
                    keys.extend(words)

        pool = self._eligible()
        best, best_score = None, 0
        for it in pool:
            name = it["name"]
            score = 0
            for i, k in enumerate(dict.fromkeys(keys)):
                if not k:
                    continue
                weight = max(1, 6 - i)
                if name == k:
                    score += 10 * weight
                elif k in name:
                    score += 5 * weight
                elif any(ch in name for ch in k):
                    score += 1
            if score > best_score:
                best, best_score = it, score

        if best is None or best_score <= 0:
            # 没有语义命中：从可用池里随机一个
            if not pool:
                return None
            best = random.choice(pool)
        if best is None:
            return None
        candidates = [it for it in pool if it["name"] == best["name"]] or [best]
        chosen = random.choice(candidates)
        self._record(chosen["name"])
        return chosen["path"]


_lib: Optional[StickerLibrary] = None


def library() -> StickerLibrary:
    global _lib
    if _lib is None:
        _lib = StickerLibrary()
    return _lib
