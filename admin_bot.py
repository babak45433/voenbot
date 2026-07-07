# -*- coding: utf-8 -*-
"""
Админ-бот. Отдельный от пользовательского, со своим токеном (ADMIN_BOT_TOKEN).

Функции:
- Получает уведомления о новых заявках (их отправляет user_bot.py через
  этот же токен), скрины приходят одной "кучкой" (media group).
- /voennik — список заявок, ожидающих проверки.
- /approved — список одобренных заявок.
- /rejected — список отклонённых заявок.
- /find <ник или номер> — поиск заявки.
- /blocklist — список заблокированных пользователей.
- Просмотр заявки: никнейм + все скрины одной кучкой.
- Кнопки "Одобрить" / "Отклонить" — меняют статус и уведомляют пользователя
  (через BOT_TOKEN — токен пользовательского бота).
- Кнопка "Заблокировать пользователя" — блокирует автора заявки.
- /block <user_id> и /unblock <user_id> — ручная блокировка по ID.

Работает с той же базой данных (db.py), что и user_bot.py — оба бота
должны указывать на один и тот же DB_PATH (один и тот же файл/том).
"""

import logging
import os

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import db

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_АДМИН_БОТА")

TWITCH_CHANNEL = "ellingtontv"
TWITCH_URL = f"https://twitch.tv/{TWITCH_CHANNEL}"

# Токен пользовательского бота — нужен ТОЛЬКО чтобы уведомить пользователя
# об одобрении/отклонении заявки. Полноценный polling для него не запускаем.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

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


async def notify_user(user_id: int, text: str):
    """Уведомляет заявителя через бота пользователей (BOT_TOKEN)."""
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN не задан — не могу уведомить пользователя %s", user_id)
        return
    try:
        applicant_bot = Bot(token=BOT_TOKEN)
        await applicant_bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.warning("Не удалось уведомить пользователя %s: %s", user_id, e)


async def send_application_card(chat_id: int, context: ContextTypes.DEFAULT_TYPE, app):
    """Отправляет никнейм + скрины кучкой (media group) + кнопки действий."""
    await context.bot.send_message(
        chat_id=chat_id, text=f"📋 Заявка №{app['id']} ({app['status']})\n{app['nickname']}"
    )

    photo_paths = [
        app["reg_screenshot"],
        app["promo_screenshot"],
        app["medcard_screenshot"],
        app["license_screenshot"],
    ]
    opened_files = []
    media = []
    for path in photo_paths:
        if path and os.path.isfile(path):
            f = open(path, "rb")
            opened_files.append(f)
            media.append(InputMediaPhoto(f))
    if media:
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media)
        finally:
            for f in opened_files:
                f.close()

    if app["status"] == "pending":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{app['id']}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{app['id']}"),
                ],
                [
                    InlineKeyboardButton(
                        "🚫 Заблокировать пользователя",
                        callback_data=f"blockuser_{app['user_id']}",
                    )
                ],
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🗑 Удалить окончательно", callback_data=f"delete_{app['id']}"
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
        chat_id=chat_id, text="Действия с заявкой:", reply_markup=keyboard
    )


# --------------------------------------------------------------------------
# КОМАНДЫ
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа к этому боту.")
        return
    await update.message.reply_text(
        "Админ-панель.\n"
        "/voennik — заявки на проверку\n"
        "/approved — одобренные заявки\n"
        "/rejected — отклонённые заявки\n"
        "/find <ник или номер> — найти заявку\n"
        "/blocklist — список заблокированных\n"
        "/block <user_id> — заблокировать пользователя\n"
        "/unblock <user_id> — разблокировать пользователя"
    )


async def _send_status_list(update: Update, status: str, title: str):
    if not is_admin(update.effective_user.id):
        return
    applications = db.get_applications_by_status(status)
    if not applications:
        await update.message.reply_text(f"{title}: пусто.")
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
        f"{title}: {len(applications)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def voennik_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_status_list(update, "pending", "Заявок на проверку")


async def approved_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_status_list(update, "approved", "Одобренные заявки")


async def rejected_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_status_list(update, "rejected", "Отклонённые заявки")


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /find <номер заявки или никнейм>\n"
            "Например: /find 42  или  /find Tema_Pupok"
        )
        return
    query = " ".join(context.args)
    results = db.search_applications(query)
    if not results:
        await update.message.reply_text("Ничего не найдено.")
        return
    if len(results) == 1:
        await send_application_card(update.effective_chat.id, context, results[0])
        return
    buttons = [
        [
            InlineKeyboardButton(
                f"№{app['id']} — {app['nickname']} ({app['status']})",
                callback_data=f"view_{app['id']}",
            )
        ]
        for app in results
    ]
    await update.message.reply_text(
        f"Найдено: {len(results)}", reply_markup=InlineKeyboardMarkup(buttons)
    )


async def blocklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    blocked = db.get_blocked_users()
    if not blocked:
        await update.message.reply_text("Заблокированных пользователей нет.")
        return
    lines = "\n".join(f"• {uid}" for uid in blocked)
    await update.message.reply_text(f"🚫 Заблокированные пользователи:\n{lines}")


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


# --------------------------------------------------------------------------
# CALLBACK-КНОПКИ
# --------------------------------------------------------------------------

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

    await send_application_card(query.message.chat_id, context, app)


async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    app_id = int(query.data.split("_")[1])
    app = db.get_application(app_id)
    if not app:
        await query.edit_message_text("Заявка не найдена.")
        return

    db.approve_application(app_id)
    await query.edit_message_text(f"✅ Заявка №{app_id} одобрена.")
    await notify_user(
        app["user_id"],
        f"✅ Ваша заявка №{app_id} одобрена!\n\n"
        f"Теперь дождитесь начала стрима на Twitch: {TWITCH_URL}\n"
        f"Как только стрим начнётся, заходите в чат и напишите: "
        f"«Я за военником, моя заявка №{app_id}».\n"
        f"После этого ожидайте выдачу. В этот момент вы должны находиться на сервере.",
    )


async def reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    app_id = int(query.data.split("_")[1])
    app = db.get_application(app_id)
    if not app:
        await query.edit_message_text("Заявка не найдена.")
        return

    db.reject_application(app_id)
    await query.edit_message_text(f"❌ Заявка №{app_id} отклонена.")
    await notify_user(
        app["user_id"],
        f"❌ Ваша заявка №{app_id} отклонена. Проверьте правильность скринов и "
        f"попробуйте подать заявку заново через /start.",
    )


async def delete_application_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    app_id = int(query.data.split("_")[1])
    db.delete_application(app_id)
    await query.edit_message_text(f"🗑 Заявка №{app_id} удалена окончательно.")


async def block_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    target_user_id = int(query.data.split("_")[1])
    db.block_user_db(target_user_id)
    await query.edit_message_text(f"🚫 Пользователь {target_user_id} заблокирован.")


def main():
    db.init_db()
    application = Application.builder().token(ADMIN_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("voennik", voennik_command))
    application.add_handler(CommandHandler("approved", approved_command))
    application.add_handler(CommandHandler("rejected", rejected_command))
    application.add_handler(CommandHandler("find", find_command))
    application.add_handler(CommandHandler("blocklist", blocklist_command))
    application.add_handler(CommandHandler("block", block_command))
    application.add_handler(CommandHandler("unblock", unblock_command))
    application.add_handler(CallbackQueryHandler(view_application, pattern="^view_"))
    application.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))
    application.add_handler(CallbackQueryHandler(reject_callback, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(delete_application_callback, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(block_user_callback, pattern="^blockuser_"))

    logger.info("Админ-бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
