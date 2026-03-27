"""
api.py — FastAPI для мини-аппа
"""
import os
import hashlib
import hmac
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from datetime import datetime, timezone

from db.catalog import get_categories, get_products, get_product
from db.cart import cart_get, wish_get
from db.users import get_user
from db.orders import create_order, get_user_orders
from db.misc import get_reviews, add_review, get_avg_rating, get_review_count
from db.promos import get_promo_by_code, check_promo_usage, apply_promo_to_price, validate_promo
from config import SHOP_NAME, SUPPORT_USERNAME, KASPI_PHONE, MANAGER_ID, BOT_TOKEN
from aiogram import Bot
from db.pool import db_run

app = FastAPI(title="ShopBot API", description="API для мини-аппа магазина")

# Инициализируем бота для отправки уведомлений менеджеру
from config import BOT_TOKEN
bot_instance = Bot(token=BOT_TOKEN)

# CORS для веб-приложения
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажите конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
async def health():
    return {"status": "API is running", "message": "✅ API работает!"}

# Отдаём index.html — Telegram открывает Mini App по этому URL
@app.get("/")
async def serve_index():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    return FileResponse(path, media_type="text/html")

# Debug info
@app.get("/debug")
async def debug_info():
    try:
        cats = await get_categories()
        cat_count = len(cats) if cats else 0
        cat_names = [c.get('name', 'N/A') for c in (cats or [])][:5]
        
        return {
            "api_status": "✅ Работает",
            "categories_count": cat_count,
            "categories_sample": cat_names,
            "message": "API и БД инициализированы"
        }
    except Exception as e:
        return {
            "api_status": "❌ Ошибка",
            "error": str(e),
            "message": "Проблема с подключением к БД"
        }

# Тестовые эндпоинты (без параметров)
@app.get("/test/categories")
async def test_categories():
    """Тестовый эндпоинт для проверки категорий"""
    try:
        cats = await get_categories()
        return {
            "success": True,
            "count": len(cats) if cats else 0,
            "data": cats[:5] if cats else []
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/test/products")
async def test_products():
    """Тестовый эндпоинт для проверки товаров"""
    try:
        if not await get_categories():
            return {"success": False, "error": "Нет категорий"}
        
        cat = (await get_categories())[0]
        prods = await get_products(cat['id'])
        return {
            "success": True,
            "category": cat['name'],
            "count": len(prods) if prods else 0,
            "data": prods[:3] if prods else []
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# Категории
@app.get("/categories")
async def get_all_categories():
    try:
        categories = await get_categories()
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/categories/{category_id}/products")
async def get_products_in_category(category_id: int):
    try:
        products = await get_products(category_id)
        return {"products": products}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Товары
@app.get("/products/{product_id}")
async def get_single_product(product_id: int):
    try:
        product = await get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"product": product}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Галерея товара
@app.get("/products/{product_id}/gallery")
async def get_product_gallery(product_id: int):
    try:
        product = await get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        import json
        gallery = []
        try:
            gallery = json.loads(product.get("gallery") or "[]")
        except Exception:
            pass
        # Include card as first image if exists
        card_fid = product.get("card_file_id", "")
        card_mt  = product.get("card_media_type", "photo")
        return {
            "gallery": gallery,
            "card_file_id": card_fid,
            "card_media_type": card_mt,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Корзина
@app.get("/cart/{user_id}")
async def get_user_cart(user_id: int):
    try:
        cart = await cart_get(user_id)
        return {"cart": cart}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Избранное
@app.get("/wishlist/{user_id}")
async def get_user_wishlist(user_id: int):
    try:
        wishlist = await wish_get(user_id)
        return {"wishlist": wishlist}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/wishlist/add")
async def add_to_wishlist(req: dict):
    try:
        from db.cart import wish_add
        user_id = req.get("user_id", 999999)
        product_id = req.get("product_id")
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id required")
        result = await wish_add(user_id, product_id)
        return {"success": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/wishlist/remove")
async def remove_from_wishlist(req: dict):
    try:
        from db.cart import wish_remove
        user_id = req.get("user_id", 999999)
        product_id = req.get("product_id")
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id required")
        await wish_remove(user_id, product_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Профиль
@app.get("/profile/{user_id}")
async def get_user_profile(user_id: int):
    try:
        user = await get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"profile": user}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# О магазине
@app.get("/store")
async def get_store_info():
    return {
        "name": SHOP_NAME,
        "support_username": SUPPORT_USERNAME,
        "kaspi_phone": KASPI_PHONE,
        "manager_id": MANAGER_ID
    }

# Поддержка
@app.get("/support")
async def get_support_info():
    return {
        "username": SUPPORT_USERNAME,
        "phone": KASPI_PHONE
    }

# Проверка промокода
@app.post("/promo/check")
async def check_promo(req: dict):
    code = (req.get("code") or "").strip().upper()
    user_id = req.get("user_id", 0)
    if not code:
        return {"valid": False, "error": "Введите промокод"}
    promo, err = await validate_promo(code, user_id)
    if not promo:
        return {"valid": False, "error": err}
    from db.promos import apply_promo_to_price as _apply
    # Calculate on dummy price to show discount info
    return {
        "valid": True,
        "promo_type": promo["promo_type"],
        "value": promo["value"],
        "description": promo["description"],
    }

# ══════════════════════════════════════════════
# ЗАКАЗЫ
# ══════════════════════════════════════════════

class OrderItem(BaseModel):
    product_id: int
    size: str
    qty: int = 1

class OrderRequest(BaseModel):
    items: list[OrderItem]
    phone: str
    address: str
    promo_code: str = ""
    method: str = "kaspi"
    user_id: int = None  # Реальный Telegram user ID

@app.post("/order/create")
async def create_order_handler(order: OrderRequest):
    try:
        if not order.items:
            return {"success": False, "error": "Корзина пуста"}

        user_id = order.user_id or 999999
        user = await get_user(user_id)

        if not user:
            await db_run(
                """INSERT INTO users(user_id, username, first_name, registered_at)
                   VALUES($1, $2, $3, $4)
                   ON CONFLICT(user_id) DO UPDATE SET username=$2, first_name=$3""",
                (user_id, "webappuser", "WebApp User", datetime.now(timezone.utc).isoformat()),
            )
            user = {"username": "", "first_name": "WebApp", "phone": "", "default_address": ""}

        # Validate promo
        discount = 0
        promo_info_text = ""
        promo_obj = None
        if order.promo_code:
            promo_obj, err = await validate_promo(order.promo_code, user_id)
            if not promo_obj:
                return {"success": False, "error": err}

        # Build order items with prices
        order_items = []
        total = 0
        for item in order.items:
            product = await get_product(item.product_id)
            if not product:
                return {"success": False, "error": f"Товар {item.product_id} не найден"}
            qty = getattr(item, 'qty', 1) or 1
            line_price = product["price"] * qty
            total += line_price
            order_items.append({
                "product_id": item.product_id,
                "name": product["name"],
                "size": item.size,
                "price": product["price"],
                "qty": qty,
            })

        # Apply promo to total
        if promo_obj:
            total_after, discount, promo_info_text = apply_promo_to_price(total, promo_obj)
        else:
            total_after = total

        # Create one order per item (existing schema)
        first_item = order_items[0]
        oid = await create_order(
            uid=user_id,
            username=user.get("username", "") or "webappuser",
            first_name=user.get("first_name", "") or "WebApp",
            pid=first_item["product_id"],
            size=first_item["size"],
            price=total_after,
            method=order.method,
            phone=order.phone,
            address=order.address,
            promo_code=order.promo_code,
            discount=discount,
        )

        if not oid:
            return {"success": False, "error": "Ошибка при создании заказа"}

        # Mark promo as used
        if promo_obj:
            from db.promos import use_promo
            await use_promo(user_id, promo_obj["id"], oid)

        # Build digital signature
        server_time = datetime.now(timezone.utc).isoformat()
        receipt_id = f"AA-{oid}-{user_id}"
        sig_payload = f"{oid}:{user_id}:{total_after}:{server_time}"
        signature = hmac.new(BOT_TOKEN.encode(), sig_payload.encode(), hashlib.sha256).hexdigest()[:32]

        # Receipt data
        receipt_data = {
            "order_id": oid,
            "receipt_id": receipt_id,
            "user_id": user_id,
            "username": user.get("username", ""),
            "created_at": server_time,
            "server_time": server_time,
            "method": order.method,
            "items": order_items,
            "total": total_after,
            "discount": discount,
            "promo_code": order.promo_code,
            "signature": signature,
            "shop_name": SHOP_NAME,
            "support": SUPPORT_USERNAME,
        }

        # Notify manager
        items_text = "\n".join(f"  • {i['name']} ({i['size']}) x{i['qty']} — {i['price']*i['qty']:,.0f} ₸" for i in order_items)
        notif = (
            f"🔔 <b>Новый заказ #{oid} (WebApp)</b>\n\n"
            f"👤 ID: <code>{user_id}</code>\n"
            f"📦 Товары:\n{items_text}\n"
            f"💰 Итого: <b>{total_after:,.0f} ₸</b>"
            + (f"\n🏷 Промокод: {order.promo_code} (-{discount:,.0f} ₸)" if discount else "")
            + f"\n📞 Телефон: {order.phone}\n📍 Адрес: {order.address}\n\n"
            f"<blockquote>⏳ Ожидается оплата через Kaspi</blockquote>"
        )
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        mgr_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"weborder_confirm_{oid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"weborder_reject_{oid}"),
        ]])
        try:
            await bot_instance.send_message(MANAGER_ID, notif, parse_mode="HTML", reply_markup=mgr_kb)
        except Exception as e:
            print(f"Manager notify error: {e}")

        # Send receipt to user via bot
        import base64
        receipt_b64 = base64.b64encode(json.dumps(receipt_data, ensure_ascii=False).encode()).decode()
        receipt_url = f"https://bot-api-production-2f78.up.railway.app/receipt?data={receipt_b64}"
        receipt_msg = (
            f"🧾 <b>Чек заказа #{oid}</b>\n\n"
            f"💰 Сумма: <b>{total_after:,.0f} ₸</b>\n"
            f"📲 Переведите на номер: <code>{KASPI_PHONE}</code>\n\n"
            f"<blockquote>После оплаты менеджер подтвердит заказ.</blockquote>"
        )
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            user_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🧾 Открыть чек", url=receipt_url)
            ]])
            await bot_instance.send_message(user_id, receipt_msg, parse_mode="HTML", reply_markup=user_kb)
        except Exception as e:
            print(f"User receipt send error: {e}")

        return {
            "success": True,
            "order_id": oid,
            "receipt": receipt_data,
            "payment_info": {
                "method": "kaspi",
                "phone": KASPI_PHONE,
                "amount": total_after,
                "description": f"Заказ #{oid}",
            },
            "message": f"✅ Заказ #{oid} создан!",
        }

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"success": False, "error": f"Ошибка сервера: {str(e)}"}

@app.get("/receipt")
async def serve_receipt(data: str = ""):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt.html")
    return FileResponse(path, media_type="text/html")


@app.get("/file-url")
async def get_file_url(file_id: str):
    """Получить публичный URL файла из Telegram по file_id"""
    try:
        file = await bot_instance.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# Заказы пользователя
@app.get("/orders")
async def get_orders_for_current_user(user_id: int = None):
    """
    Получить заказы пользователя (требует user_id в query параметре или заголовке)
    """
    try:
        if user_id is None:
            # Пробуем получить из куки или заголовка (если будет реализовано)
            return {"orders": []}
        
        orders = await get_user_orders(user_id)
        return {"orders": orders or []}
    except Exception as e:
        return {"orders": []}

@app.get("/orders/{user_id}")
async def get_user_orders_endpoint(user_id: int):
    """
    Получить все заказы пользователя по его ID
    """
    try:
        orders = await get_user_orders(user_id)
        
        # Форматируем заказы для фронтенда
        formatted_orders = []
        for order in orders:
            formatted_orders.append({
                "id": order.get("id"),
                "created_at": order.get("created_at"),
                "status": order.get("status"),
                "pname": order.get("product_name"),
                "size": order.get("size"),
                "price": order.get("price"),
            })
        
        return {"orders": formatted_orders}
    except Exception as e:
        print(f"❌ Ошибка при получении заказов: {e}")
        return {"orders": []}


# ══════════════════════════════════════════════
# ОТЗЫВЫ
# ══════════════════════════════════════════════

@app.get("/products/{product_id}/reviews")
async def get_product_reviews(product_id: int, limit: int = 20):
    try:
        reviews = await get_reviews(product_id, limit=limit)
        avg = await get_avg_rating(product_id)
        count = await get_review_count(product_id)
        return {
            "reviews": [
                {
                    "id": r.get("id"),
                    "user_id": r.get("user_id"),
                    "username": r.get("username") or "",
                    "first_name": r.get("first_name") or "Покупатель",
                    "rating": r.get("rating"),
                    "comment": r.get("comment"),
                    "photo_file_id": r.get("photo_file_id") or "",
                    "created_at": r.get("created_at"),
                }
                for r in reviews
            ],
            "avg_rating": avg,
            "count": count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ReviewRequest(BaseModel):
    user_id: int
    order_id: int = 0
    rating: int
    comment: str
    photo_file_id: str = ""

@app.post("/products/{product_id}/reviews")
async def post_product_review(product_id: int, req: ReviewRequest):
    try:
        if not 1 <= req.rating <= 5:
            raise HTTPException(status_code=400, detail="rating must be 1-5")
        if not req.comment.strip():
            raise HTTPException(status_code=400, detail="comment required")
        if len(req.comment.strip()) < 80:
            raise HTTPException(status_code=400, detail="Минимум 80 символов в отзыве")
        await add_review(req.user_id, product_id, req.order_id, req.rating, req.comment.strip(), req.photo_file_id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
