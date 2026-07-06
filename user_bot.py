# -*- coding: utf-8 -*-
"""
Пользовательский бот "Военный билет".

Только диалог с пользователем: /start -> Да/Нет -> сбор скриншотов и ника ->
номер заявки. Уведомление о новой заявке отправляется через ОТДЕЛЬНЫЙ
админ-бот (ADMIN_BOT_TOKEN) — админы видят заявки там, а не здесь.

Все админ-команды (/voennik, /block, /unblock и т.д.) находятся в
admin_bot.py — это два разных бота с разными токенами.
"""

import logging
import os
import re

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db

# --------------------------------------------------------------------------
# НАСТРОЙКИ
# --------------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_ПОЛЬЗОВАТЕЛЬСКОГО_БОТА")

# Токен АДМИН-бота — нужен, чтобы отправлять уведомления о новых заявках
# именно туда, а не в этот бот.
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_АДМИН_БОТА")

_admin_ids_env = os.getenv("ADMIN_IDS")
if _admin_ids_env:
    ADMIN_IDS = [int(x.strip()) for x in _admin_ids_env.split(",") if x.strip()]
else:
    ADMIN_IDS = [111111111, 222222222]

DAYS_TO_ACTIVATE = int(os.getenv("DAYS_TO_ACTIVATE", "7"))

SERVER_NAME = "12 сервер Radmir RP"
PROMOCODE = "SUETA"
TWITCH_CHANNEL = "ellingtontv"
TWITCH_URL = f"https://twitch.tv/{TWITCH_CHANNEL}"

(
    ASK_NEED,
    REG_SCREENSHOT,
    PROMO_SCREENSHOT,
    MEDCARD_SCREENSHOT,
    NICKNAME,
    LICENSE_SCREENSHOT,
) = range(6)

NICKNAME_PATTERN = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]+_[A-ZА-ЯЁ][a-zа-яё]+$")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def format_hms(td) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours} ч {minutes} мин"


async def save_photo(context: ContextTypes.DEFAULT_TYPE, photo, prefix: str) -> str:
    """
    Скачивает фото на диск (в общую папку на Azure File Share) и возвращает
    путь к файлу. Так фото сможет позже открыть и переслать ДРУГОЙ бот
    (admin_bot) — обычный file_id для этого не годится, он привязан к
    тому боту, который изначально получил фото.
    """
    file = await context.bot.get_file(photo.file_id)
    filename = f"{prefix}_{photo.file_unique_id}.jpg"
    path = os.path.join(db.PHOTOS_DIR, filename)
    await file.download_to_drive(path)
    return path


async def blocked_guard(update: Update) -> bool:
    user_id = update.effective_user.id
    if db.is_blocked(user_id):
        if update.message:
            await update.message.reply_text(
                "🚫 Вы заблокированы администрацией и не можете пользоваться ботом."
            )
        return True
    return False


# --------------------------------------------------------------------------
# ДИАЛОГ
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END

    context.user_data.clear()
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Да", callback_data="need_yes"),
                InlineKeyboardButton("Нет", callback_data="need_no"),
            ]
        ]
    )
    await update.message.reply_text(
        f"✨ Военный билет на {SERVER_NAME} 🎖\n\nВам нужен военный билет?",
        reply_markup=keyboard,
    )
    return ASK_NEED


async def need_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "need_no":
        await query.edit_message_text(
            "Хорошо, если передумаете — просто отправьте /start снова."
        )
        return ConversationHandler.END

    remaining = db.get_cooldown_remaining(user_id)
    if remaining is not None:
        await query.edit_message_text(
            "⏳ Вы недавно уже подавали заявку.\n"
            f"Попробуйте снова через {format_hms(remaining)}."
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "Отлично! Отправьте скриншот введённого ника при регистрации.\n\n"
        "⚠️ Внимательно проверьте ник при вводе — проверка идёт через "
        "команду /referals в игре, без этого выдачи не будет."
    )
    return REG_SCREENSHOT


async def reg_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text(
            "Нужен именно скриншот (фото). Отправьте скрин ника при регистрации."
        )
        return REG_SCREENSHOT
    context.user_data["reg_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{update.effective_user.id}_reg"
    )
    await update.message.reply_text("Отправьте скриншот введённого промокода sueta.")
    return PROMO_SCREENSHOT


async def promo_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text(
            "Нужен именно скриншот (фото). Отправьте скрин промокода sueta."
        )
        return PROMO_SCREENSHOT
    context.user_data["promo_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{update.effective_user.id}_promo"
    )
    await update.message.reply_text("Отправьте скриншот мед. карты.")
    return MEDCARD_SCREENSHOT


async def medcard_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text(
            "Нужен именно скриншот (фото). Отправьте скрин мед. карты."
        )
        return MEDCARD_SCREENSHOT
    context.user_data["medcard_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{update.effective_user.id}_medcard"
    )
    await update.message.reply_text(
        "Введите ваш никнейм строго по форме, например: Tema_Pupok"
    )
    return NICKNAME


async def nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if not NICKNAME_PATTERN.match(text):
        await update.message.reply_text(
            "❌ Неверный формат. Нужно вида Слово_Слово с заглавных букв, "
            "например: Tema_Pupok.\nПопробуйте ещё раз."
        )
        return NICKNAME
    context.user_data["nickname"] = text
    await update.message.reply_text("Отправьте скриншот лицензии на оружие.")
    return LICENSE_SCREENSHOT


async def license_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text(
            "Нужен именно скриншот (фото). Отправьте скрин лицензии на оружие."
        )
        return LICENSE_SCREENSHOT

    context.user_data["license_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{update.effective_user.id}_license"
    )

    user = update.effective_user
    data = {
        "user_id": user.id,
        "username": user.username or user.full_name,
        "nickname": context.user_data["nickname"],
        "reg_screenshot": context.user_data["reg_screenshot"],
        "promo_screenshot": context.user_data["promo_screenshot"],
        "medcard_screenshot": context.user_data["medcard_screenshot"],
        "license_screenshot": context.user_data["license_screenshot"],
    }
    app_id = db.save_application(data)

    await update.message.reply_text(
        f"✅ Заявка №{app_id} принята!\n\n"
        f"Ожидайте проверки вашей формы.\n"
        f"Примечание: даётся {DAYS_TO_ACTIVATE} дней после отыгровки промокода "
        f"{PROMOCODE}, чтобы получить военный билет.\n\n"
        f"📌 Что вас ждёт на {SERVER_NAME}:\n"
        f"💸 70.000$ при регистрации (+100.000$ от организатора)\n"
        f"👑 GOLD VIP статус\n"
        f"🚗 BMW G30 540i от сервера\n"
        f"🎖 Военный билет\n\n"
        f"Для получения бонусов зайдите на стрим на Twitch и назовите номер "
        f"вашей заявки: №{app_id}.\n"
        f"👉 {TWITCH_URL}",
        disable_web_page_preview=True,
    )

    await notify_admin_bot(app_id)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Процесс отменён. Начать заново — /start.")
    return ConversationHandler.END


# --------------------------------------------------------------------------
# УВЕДОМЛЕНИЕ АДМИН-БОТА О НОВОЙ ЗАЯВКЕ
# --------------------------------------------------------------------------

async def notify_admin_bot(app_id: int):
    """
    Отправляет никнейм и скрины админам, но НЕ через этого бота, а через
    отдельный админ-бот (свой токен) — поэтому создаём отдельный Bot()
    без запуска polling, просто чтобы разово отправить сообщения.
    """
    app = db.get_application(app_id)
    if not app:
        return

    photo_paths = [
        app["reg_screenshot"],
        app["promo_screenshot"],
        app["medcard_screenshot"],
        app["license_screenshot"],
    ]

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑 Удалить (проверено)", callback_data=f"delete_{app_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🚫 Заблокировать пользователя",
                    callback_data=f"blockuser_{app['user_id']}",
                )
            ],
        ]
    )

    admin_bot = Bot(token=ADMIN_BOT_TOKEN)
    for admin_id in ADMIN_IDS:
        try:
            await admin_bot.send_message(chat_id=admin_id, text=app["nickname"])
            for path in photo_paths:
                with open(path, "rb") as photo_file:
                    await admin_bot.send_photo(chat_id=admin_id, photo=photo_file)
            await admin_bot.send_message(
                chat_id=admin_id, text="Действия с заявкой:", reply_markup=keyboard
            )
        except Exception as e:
            logger.warning("Не удалось отправить админу %s: %s", admin_id, e)


# --------------------------------------------------------------------------
# ЗАПУСК
# --------------------------------------------------------------------------

def main():
    db.init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NEED: [CallbackQueryHandler(need_answer, pattern="^need_")],
            REG_SCREENSHOT: [MessageHandler(filters.PHOTO | filters.TEXT, reg_screenshot)],
            PROMO_SCREENSHOT: [MessageHandler(filters.PHOTO | filters.TEXT, promo_screenshot)],
            MEDCARD_SCREENSHOT: [MessageHandler(filters.PHOTO | filters.TEXT, medcard_screenshot)],
            NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, nickname)],
            LICENSE_SCREENSHOT: [MessageHandler(filters.PHOTO | filters.TEXT, license_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    logger.info("Пользовательский бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
