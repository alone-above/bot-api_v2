"""handlers/reviews.py — Отзывы на товар"""
from aiogram import Bot, Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ae
from db import get_reviews, add_review, get_product, is_banned
from keyboards import btn, kb

router = Router()


class ReviewSt(StatesGroup):
    rating  = State()
    comment = State()
    photo   = State()


# ── Показ отзывов ─────────────────────────────────────
@router.callback_query(F.data.startswith("reviews_"))
async def cb_reviews(cb: types.CallbackQuery):
    pid     = int(cb.data.split("_")[1])
    reviews = await get_reviews(pid, limit=10)

    stars_map = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}

    if not reviews:
        text = f"{ae('star')} <b>Отзывы о товаре</b>\n\n<blockquote>Отзывов пока нет. Станьте первым!</blockquote>"
    else:
        text = f"{ae('star')} <b>Отзывы о товаре</b>\n\n━━━━━━━━━━━━━━━━━\n"
        for rv in reviews:
            stars = stars_map.get(rv["rating"], "")
            dt    = (rv["created_at"] or "")[:10]
            name  = rv.get("first_name") or "Покупатель"
            uname = f" @{rv['username']}" if rv.get("username") else ""
            text += f"<b>{stars}</b>  <b>{name}</b>{uname}  <i>{dt}</i>\n{rv['comment']}\n\n"
        text += "━━━━━━━━━━━━━━━━━"

    markup = kb([btn("К товару", f"prod_{pid}", icon="back")])
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await cb.answer()


# ── Начало написания отзыва (после подтверждения заказа) ──
@router.callback_query(F.data.startswith("leave_review_"))
async def cb_leave_review(cb: types.CallbackQuery, state: FSMContext):
    if await is_banned(cb.from_user.id):
        await cb.answer("🚫", show_alert=True)
        return
    parts = cb.data.split("_")
    pid = int(parts[2])
    oid = int(parts[3])
    p   = await get_product(pid)
    await state.update_data(review_pid=pid, review_oid=oid)
    await state.set_state(ReviewSt.rating)

    rows = [
        [btn("⭐", "rv_1"), btn("⭐⭐", "rv_2"), btn("⭐⭐⭐", "rv_3"),
         btn("⭐⭐⭐⭐", "rv_4"), btn("⭐⭐⭐⭐⭐", "rv_5")],
        [btn("Отмена", "main", icon="back")],
    ]
    text = (
        f"{ae('star')} <b>Оставить отзыв</b>\n\n"
        f"<blockquote>Товар: <b>{p['name'] if p else '—'}</b>\n\n"
        f"Выберите оценку:</blockquote>"
    )
    try:
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=kb(*rows, include_main=False))
    except Exception:
        await cb.message.answer(text, parse_mode="HTML",
                                reply_markup=kb(*rows, include_main=False))
    await cb.answer()


@router.callback_query(ReviewSt.rating, F.data.startswith("rv_"))
async def cb_review_rating(cb: types.CallbackQuery, state: FSMContext):
    rating = int(cb.data.split("_")[1])
    await state.update_data(review_rating=rating)
    await state.set_state(ReviewSt.comment)
    stars = "⭐" * rating
    await cb.message.edit_text(
        f"{ae('star')} <b>Оценка: {stars}</b>\n\n"
        f"<blockquote>Напишите отзыв (минимум 80 символов).\n"
        f"Расскажите о качестве, доставке, впечатлениях.</blockquote>",
        parse_mode="HTML",
        reply_markup=kb([btn("Отмена", "main", icon="back")], include_main=False),
    )
    await cb.answer()


@router.message(ReviewSt.comment)
async def proc_review_comment(msg: types.Message, state: FSMContext):
    comment = msg.text.strip() if msg.text else ""
    if len(comment) < 80:
        await msg.answer(
            f"⚠️ Слишком коротко ({len(comment)} симв.). Минимум 80 символов.\n"
            f"Напишите подробнее:",
        )
        return
    await state.update_data(review_comment=comment)
    await state.set_state(ReviewSt.photo)
    await msg.answer(
        f"{ae('sparkle')} <b>Отлично!</b>\n\n"
        f"<blockquote>Прикрепите фото товара (необязательно) "
        f"или отправьте <b>—</b> чтобы пропустить.</blockquote>",
        parse_mode="HTML",
        reply_markup=kb([btn("Пропустить", "rv_skip_photo", icon="ok")], include_main=False),
    )


@router.callback_query(ReviewSt.photo, F.data == "rv_skip_photo")
async def cb_skip_photo(cb: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _save_review(cb.from_user, state, bot, photo_file_id="")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer()


@router.message(ReviewSt.photo)
async def proc_review_photo(msg: types.Message, state: FSMContext, bot: Bot):
    photo_file_id = ""
    if msg.photo:
        photo_file_id = msg.photo[-1].file_id
    elif msg.text and msg.text.strip() == "—":
        pass
    else:
        await msg.answer("Отправьте фото или <b>—</b> чтобы пропустить.", parse_mode="HTML")
        return
    await _save_review(msg.from_user, state, bot, photo_file_id=photo_file_id)


async def _save_review(user, state: FSMContext, bot: Bot, photo_file_id: str = ""):
    d       = await state.get_data()
    pid     = d.get("review_pid")
    oid     = d.get("review_oid", 0)
    rating  = d.get("review_rating", 5)
    comment = d.get("review_comment", "")
    await state.clear()

    if not pid:
        return

    await add_review(user.id, pid, oid, rating, comment, photo_file_id)

    p = await get_product(pid)
    stars = "⭐" * rating
    text = (
        f"{ae('confetti')} <b>Отзыв опубликован!</b>\n\n"
        f"<blockquote>{stars}\n{comment[:100]}{'...' if len(comment) > 100 else ''}</blockquote>"
    )
    try:
        await bot.send_message(user.id, text, parse_mode="HTML",
                               reply_markup=kb([btn("К товару", f"prod_{pid}", icon="bag")]))
    except Exception:
        pass
