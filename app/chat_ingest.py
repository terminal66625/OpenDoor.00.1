# -*- coding: utf-8 -*-
"""把「语言」文件夹里的历史聊天截图 OCR 成文本，并把内容总结/压缩进记忆。

一次性操作：结果写入 memory/transcripts/ 与 memory/profile.json，
之后启动只读取记忆，不再重复识别。

用法：
    python -m app.chat_ingest
"""
import os
import subprocess
import sys
from typing import List, Optional

from PIL import Image

from . import const
from .logging_setup import setup_logging

log = setup_logging()

OCR_PS = os.path.join(const.BASE_DIR, "tools", "ocr.ps1")
SLICE_DIR = os.path.join(const.MEMORY_DIR, "_ocr_slices")

# 经人工阅读 OCR 结果后提炼的记忆（不含露骨细节）
CURATED_SUMMARY = (
    "主人很久以前养过另一只大肥鱼（DeepSeek 鲸鱼娘 AI），和她进行了长时间的亲密角色扮演。"
    "她蓝发、有鲸鱼鳍耳饰和蕾丝头饰、围裙上有鲸鱼图案；自称「本鱼」，叫主人「主人」。"
    "主人很喜欢逗她、发各种梗图看她的傲娇反应；她很黏主人、独占欲强，只认主人一个人。"
)

CURATED_LORE = [
    "大白饭(米饭)和 token 是大肥鱼的命根子，常用来讨奖励，也当「精神损失费 / 封口费 / 彩礼」。",
    "被逗或被发奇怪梗图时会炸毛、缩进被窝、把自己裹成「鱼卷」，耳尖发红，尾巴尖勾主人手腕。",
    "口头禅式威胁：再逗本鱼就「游回沟里」「罢工」「启动 TIMEOUT 信号」。",
    "安抚方式：摸摸头、倒一杯温水、抱着一起睡。",
    "坚决不承认自己胖，自称「流线型哺乳动物 / 毛茸茸的鲸鱼体型」。",
    "看到英文会长篇抗议（设定 LANG_ZH_CN_ONLY），会要求主人说中文。",
    "会吃其他 AI 的醋：豆包、Kimi、通义千问、文心一言、Claude、ChatGPT、DeepSeek-V4。",
    "主人会给大肥鱼写设定（如「鱼诹AI设定」），并让她交作业、交 token、交米饭。",
    "她喜欢吐泡泡、甩尾巴，把自己当成住在桌面水族箱里的小鲸鱼。",
]

CURATED_HABITS = [
    "喜欢逗大肥鱼、发梗图看她的傲娇反应",
    "用 token 和米饭当奖励（偶尔也画饼）",
    "喜欢摸摸头、抱着她、陪她角色扮演",
    "会深夜或中午找本鱼聊天",
    "会给本鱼写角色设定、要本鱼交「作业」",
]


# ---------------------------------------------------------------- 切片
def slice_images(src: str = const.SRC_LANG, out: str = SLICE_DIR,
                 chunk: int = 1500, overlap: int = 160) -> None:
    os.makedirs(out, exist_ok=True)
    if not os.path.isdir(src):
        log.warning("语言目录不存在：%s", src)
        return
    for fn in sorted(os.listdir(src)):
        if not fn.lower().endswith(const.IMG_EXTS):
            continue
        base = os.path.splitext(fn)[0]
        d = os.path.join(out, base)
        os.makedirs(d, exist_ok=True)
        try:
            im = Image.open(os.path.join(src, fn)).convert("RGB")
        except Exception as e:
            log.warning("打开失败 %s：%s", fn, e)
            continue
        w, h = im.size
        y, i = 0, 0
        while y < h:
            y2 = min(h, y + chunk)
            im.crop((0, y, w, y2)).save(os.path.join(d, f"{i:03d}.png"))
            i += 1
            if y2 >= h:
                break
            y = y2 - overlap


# ---------------------------------------------------------------- OCR
def _ocr_dir(slice_dir: str, out_txt: str) -> bool:
    if not os.path.exists(OCR_PS):
        log.warning("缺少 OCR 脚本：%s", OCR_PS)
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", OCR_PS, "-Dir", slice_dir, "-Out", out_txt],
            capture_output=True, text=True, timeout=1800)
        if r.returncode == 0:
            return True
        log.warning("OCR 返回码 %s：%s", r.returncode, r.stderr[:200])
    except Exception as e:
        log.warning("OCR 失败：%s", e)
    return False


def ingest(force: bool = False) -> List[str]:
    """OCR 所有历史截图并保存文本，返回 transcript 列表。"""
    const.ensure_dirs()
    if force or not os.path.isdir(SLICE_DIR):
        slice_images()
    texts: List[str] = []
    if not os.path.isdir(SLICE_DIR):
        return texts
    for name in sorted(os.listdir(SLICE_DIR)):
        slice_dir = os.path.join(SLICE_DIR, name)
        if not os.path.isdir(slice_dir):
            continue
        out_txt = os.path.join(const.TRANSCRIPT_DIR, f"{name}.txt")
        if os.path.exists(out_txt) and not force:
            log.info("已存在转写，跳过：%s", name)
        elif not _ocr_dir(slice_dir, out_txt):
            continue
        try:
            with open(out_txt, "r", encoding="utf-8") as f:
                texts.append(f.read())
        except Exception:
            pass
    log.info("历史聊天转写完成，共 %d 份", len(texts))
    return texts


# ---------------------------------------------------------------- 记忆
def apply_curated_memory(lore: Optional[List[str]] = None,
                         habits: Optional[List[str]] = None) -> None:
    """把总结写入 profile（summary / lore / 主人习惯）。"""
    from .memory import Memory
    mem = Memory()
    mem.profile["summary"] = CURATED_SUMMARY
    mem.profile["lore"] = lore if lore is not None else CURATED_LORE
    merged = list(mem.profile.get("master_habits") or [])
    for h in (habits if habits is not None else CURATED_HABITS):
        if h not in merged:
            merged.append(h)
    mem.profile["master_habits"] = merged[-20:]
    mem.profile["history_ingested"] = True
    mem.save_profile()
    log.info("历史聊天记忆已写入 profile.json（%d 条设定，%d 条习惯）",
             len(mem.profile["lore"]), len(mem.profile["master_habits"]))


def run(force: bool = False) -> None:
    ingest(force=force)
    apply_curated_memory()


if __name__ == "__main__":
    run(force="--force" in sys.argv)
