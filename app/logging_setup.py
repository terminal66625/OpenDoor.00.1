# -*- coding: utf-8 -*-
"""日志初始化：按日期滚动到 logs/，并提供 Key 脱敏过滤器。"""
import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler

from . import const
from .util import mask_key

_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


class _MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if "sk-" in msg:
                record.msg = _KEY_RE.sub(lambda m: mask_key(m.group(0)), msg)
                record.args = ()
        except Exception:
            pass
        return True


def setup_logging() -> logging.Logger:
    const.ensure_dirs()
    logger = logging.getLogger("dafeiyu")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    fh = TimedRotatingFileHandler(
        os.path.join(const.LOG_DIR, "dafeiyu.log"),
        when="midnight", backupCount=14, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(_MaskFilter())
    logger.addHandler(fh)

    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.addFilter(_MaskFilter())
        logger.addHandler(sh)
    except Exception:
        pass

    # 未捕获异常写入日志（否则 pythonw/打包版崩溃时看不到原因）
    def _excepthook(tp, val, tb):
        try:
            logger.error("未捕获异常：", exc_info=(tp, val, tb))
        except Exception:
            pass
    try:
        sys.excepthook = _excepthook
        import threading

        def _thread_hook(args):
            try:
                name = args.thread.name if args.thread else "?"
                logger.error("线程未捕获异常（%s）：", name,
                             exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            except Exception:
                pass
        threading.excepthook = _thread_hook
    except Exception:
        pass
    return logger


# 让 Windows 控制台也支持中文输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass
