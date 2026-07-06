# -*- coding: utf-8 -*-
"""
Админ-бот. Отдельный от пользовательского, со своим токеном (ADMIN_BOT_TOKEN).

Функции:
- Получает уведомления о новых заявках (их отправляет user_bot.py через
  этот же токен).
- /voennik — список заявок, ожидающих проверки.
- Просмотр заявки: никнейм + все скрины.
- Кнопка "Удалить (проверено)" — удаляет заявку из базы.
- Кнопка "Заблокировать пользователя" — блокирует автора заявки.
- /block <user_id> и /unblock <user_id> — ручная блокировка по ID.

Работает с той же базой данных (db.py), что и user_bot.py — оба бота
должны указывать на один и тот же DB_PATH (один и тот же файл/том).
"""

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import db

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_АДМИН_БОТА")

_admin_ids_env = os.getenv("ADMIN_IDS")
if _admin_ids_env:
    ADMIN_IDS = [int(x.strip()) for x in _admin_ids_env.split(",") if x.strip()]
else:
    ADMIN_IDS = [111111111, 222222222]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа к этому боту.")
        return
    await update.message.reply_text(
        "Админ-панель.\n"
        "/voennik — список заявок на проверку\n"
        "/block <user_id> — заблокировать пользователя\n"
        "/unblock <user_id> — разблокировать пользователя"
    )


async def voennik_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    applications = db.get_pending_applications()
    if not applications:
        await update.message.reply_text("Заявок на проверку нет.")
        return

    buttons = [
        [
            InlineKeyboardButton(
                f"Заявка №{app['id']} — {app['nickname']}",
                callback_data=f"view_{app['id']}",
            )
        ]
        for app in applications
    ]
    await update.message.reply_text(
        f"Заявок на проверку: {len(applications)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def view_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        return

    app_id = int(query.data.split("_")[1])
    app = db.get_application(app_id)
    if not app:
        await query.edit_message_text("Заявка не найдена (возможно, уже удалена).")
        return

    await context.bot.send_message(chat_id=query.message.chat_id, text=app["nickname"])

    photos = [
        app["reg_screenshot"],
        app["promo_screenshot"],
        app["medcard_screenshot"],
        app["license_screenshot"],
    ]
    for file_id in photos:
        await context.bot.send_photo(chat_id=query.message.chat_id, photo=file_id)

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
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Действия с заявкой:",
        reply_markup=keyboard,
    )


async def delete_application_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        return

    app_id = int(query.data.split("_")[1])
    db.delete_application(app_id)
    await query.edit_message_text(f"✅ Заявка №{app_id} удалена (отмечена как прочитанная).")


async def block_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        return

    target_user_id = int(query.data.split("_")[1])
    db.block_user_db(target_user_id)
    await query.edit_message_text(f"🚫 Пользователь {target_user_id} заблокирован.")


async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /block <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id должен быть числом.")
        return
    db.block_user_db(target_id)
    await update.message.reply_text(f"🚫 Пользователь {target_id} заблокирован.")


async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /unblock <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id должен быть числом.")
        return
    db.unblock_user_db(target_id)
    await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован.")


def main():
    db.init_db()
    application = Application.builder().token(ADMIN_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("voennik", voennik_command))
    application.add_handler(CommandHandler("block", block_command))
    application.add_handler(CommandHandler("unblock", unblock_command))
    application.add_handler(CallbackQueryHandler(view_application, pattern="^view_"))
    application.add_handler(CallbackQueryHandler(delete_application_callback, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(block_user_callback, pattern="^blockuser_"))

    logger.info("Админ-бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
