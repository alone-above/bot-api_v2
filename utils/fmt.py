"""utils/fmt.py — Форматирование цен, дат, статусов"""
from datetime import datetime
from config import ORDER_STATUS_LABELS


def fmt_dt() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def fmt_price(kzt) -> str:
    try:
        return f"{int(float(kzt)):,}".replace(",", " ") + " ₸"
    except Exception:
        return f"{kzt} ₸"


def order_status_text(status: str) -> str:
    return ORDER_STATUS_LABELS.get(status, status)


async def safe_edit(msg, text: str, parse_mode: str = "HTML", reply_markup=None):
    """Безопасно редактирует или заменяет сообщение.
    
    Если сообщение содержит медиа — удаляет и отправляет новое текстовое.
    Если редактирование не удалось — удаляет и отправляет новое.
    """
    try:
        if msg.photo or msg.video or msg.animation or msg.document:
            await msg.delete()
            await msg.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            await msg.delete()
        except Exception:
            pass
        try:
            await msg.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            pass
