# -*- coding: utf-8 -*-
"""
Пользовательский бот "Военный билет".

Диалог с пользователем: /start -> Да/Нет -> сбор скриншотов и ника ->
номер заявки. Уведомление о новой заявке отправляется через ОТДЕЛЬНЫЙ
админ-бот (ADMIN_BOT_TOKEN) — админы видят заявки там, а не здесь.

Фичи:
- Индикатор прогресса "Шаг X из 5" в каждом сообщении.
- Кнопка "◀️ Назад" — вернуться на предыдущий шаг.
- Авто-напоминание через REMINDER_HOURS часов бездействия.
- Автосброс прогресса через TIMEOUT_HOURS часов бездействия
  (используется встроенный conversation_timeout из python-telegram-bot).

Все админ-команды (/voennik, /block, /unblock и т.д.) находятся в
admin_bot.py — это два разных бота с разными токенами.
"""

import logging
import os
import re

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
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

# Через сколько часов бездействия напомнить, что заявка не закончена
REMINDER_HOURS = float(os.getenv("REMINDER_HOURS", "2"))
# Через сколько часов бездействия сбросить прогресс полностью
TIMEOUT_HOURS = float(os.getenv("TIMEOUT_HOURS", "7"))

SERVER_NAME = "12 сервер Radmir RP"
PROMOCODE = "SUETA"
TWITCH_CHANNEL = "ellingtontv"
TWITCH_URL = f"https://twitch.tv/{TWITCH_CHANNEL}"

# Примеры скринов — показываются рядом с каждым запросом.
EXAMPLE_REG = "https://ibb.co/FpGr32H"
EXAMPLE_PROMO = "https://ibb.co/cS2t9bc5"
EXAMPLE_MEDCARD = "https://ibb.co/n8VPF4Gv"
EXAMPLE_LICENSE = "https://ibb.co/gMCZ3gvF"

STEP_TOTAL = 5
BACK_BUTTON_TEXT = "◀️ Назад"
BACK_MARKUP = ReplyKeyboardMarkup([[BACK_BUTTON_TEXT]], resize_keyboard=True)

(
    ASK_NEED,
    REG_SCREENSHOT,
    PROMO_SCREENSHOT,
    MEDCARD_SCREENSHOT,
    NICKNAME,
    LICENSE_SCREENSHOT,
) = range(6)

NICKNAME_PATTERN = db.NICKNAME_PATTERN

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


def step_header(n: int) -> str:
    return f"📍 Шаг {n} из {STEP_TOTAL}\n\n"


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
                "🚫 Вы заблокированы администрацией и не можете пользоваться ботом.",
                reply_markup=ReplyKeyboardRemove(),
            )
        return True
    return False


# --------------------------------------------------------------------------
# АВТО-НАПОМИНАНИЕ / ТАЙМАУТ
# --------------------------------------------------------------------------

def cancel_reminder(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f"reminder_{user_id}"):
            job.schedule_removal()


def schedule_reminder(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    cancel_reminder(context, user_id)
    if context.job_queue:
        context.job_queue.run_once(
            reminder_callback,
            REMINDER_HOURS * 3600,
            chat_id=user_id,
            name=f"reminder_{user_id}",
        )


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Вы не закончили заявку на военный билет.\n"
        "Хотите продолжить? Просто отправьте следующий скриншот/сообщение, "
        "либо напишите /cancel, чтобы отменить.",
    )


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id if update and update.effective_chat else None
    if chat_id:
        cancel_reminder(context, chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="⌛ Ваш прогресс завершён из-за неактивности.\n"
            "Начните заново — /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
    context.user_data.clear()
    return ConversationHandler.END


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
        f"✨ Военный билет на {SERVER_NAME} 🎖\n\n<b>Вам нужен военный билет?</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
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
        step_header(1) + "Отлично! <b>Отправьте скриншот введённого ника при регистрации.</b>\n\n"
        "⚠️ Внимательно проверьте ник при вводе — проверка идёт через "
        "команду /referals в игре, без этого выдачи не будет.\n\n"
        f"📎 Пример: {EXAMPLE_REG}",
        parse_mode="HTML",
    )
    # Клавиатуру с кнопкой "Назад" отдельным сообщением — у edit_message_text
    # нет возможности прикрепить ReplyKeyboardMarkup.
    await context.bot.send_message(
        chat_id=user_id, text="Готов принять скриншот 👇", reply_markup=BACK_MARKUP
    )
    schedule_reminder(context, user_id)
    return REG_SCREENSHOT


async def reg_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    user_id = update.effective_user.id

    if update.message.text == BACK_BUTTON_TEXT:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Да", callback_data="need_yes"),
                    InlineKeyboardButton("Нет", callback_data="need_no"),
                ]
            ]
        )
        await update.message.reply_text(
            f"✨ Военный билет на {SERVER_NAME} 🎖\n\n<b>Вам нужен военный билет?</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
        await update.message.reply_text("Выберите вариант:", reply_markup=keyboard)
        return ASK_NEED

    if not update.message.photo:
        await update.message.reply_text(
            step_header(1) + "Нужен именно скриншот (фото). <b>Отправьте скрин ника при регистрации.</b>",
            parse_mode="HTML",
        )
        return REG_SCREENSHOT

    context.user_data["reg_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{user_id}_reg"
    )
    await update.message.reply_text(
        step_header(2) + f"<b>Отправьте скриншот введённого промокода sueta.</b>\n\n📎 Пример: {EXAMPLE_PROMO}",
        parse_mode="HTML",
    )
    schedule_reminder(context, user_id)
    return PROMO_SCREENSHOT


async def promo_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    user_id = update.effective_user.id

    if update.message.text == BACK_BUTTON_TEXT:
        await update.message.reply_text(
            step_header(1) + f"<b>Отправьте скриншот введённого ника при регистрации.</b>\n\n"
            f"📎 Пример: {EXAMPLE_REG}",
            parse_mode="HTML",
        )
        return REG_SCREENSHOT

    if not update.message.photo:
        await update.message.reply_text(
            step_header(2) + "Нужен именно скриншот (фото). <b>Отправьте скрин промокода sueta.</b>",
            parse_mode="HTML",
        )
        return PROMO_SCREENSHOT

    context.user_data["promo_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{user_id}_promo"
    )
    await update.message.reply_text(
        step_header(3) + f"<b>Отправьте скриншот мед. карты.</b>\n\n📎 Пример: {EXAMPLE_MEDCARD}",
        parse_mode="HTML",
    )
    schedule_reminder(context, user_id)
    return MEDCARD_SCREENSHOT


async def medcard_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    user_id = update.effective_user.id

    if update.message.text == BACK_BUTTON_TEXT:
        await update.message.reply_text(
            step_header(2) + f"<b>Отправьте скриншот введённого промокода sueta.</b>\n\n📎 Пример: {EXAMPLE_PROMO}",
            parse_mode="HTML",
        )
        return PROMO_SCREENSHOT

    if not update.message.photo:
        await update.message.reply_text(
            step_header(3) + "Нужен именно скриншот (фото). <b>Отправьте скрин мед. карты.</b>",
            parse_mode="HTML",
        )
        return MEDCARD_SCREENSHOT

    context.user_data["medcard_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{user_id}_medcard"
    )
    await update.message.reply_text(
        step_header(4) + "<b>Введите ваш никнейм строго по форме, например: Tema_Pupok</b>",
        parse_mode="HTML",
    )
    schedule_reminder(context, user_id)
    return NICKNAME


async def nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if text == BACK_BUTTON_TEXT:
        await update.message.reply_text(
            step_header(3) + f"<b>Отправьте скриншот мед. карты.</b>\n\n📎 Пример: {EXAMPLE_MEDCARD}",
            parse_mode="HTML",
        )
        return MEDCARD_SCREENSHOT

    if not NICKNAME_PATTERN.match(text):
        await update.message.reply_text(
            step_header(4) + "❌ Неверный формат. <b>Нужно вида Слово_Слово с заглавных букв, "
            "например: Tema_Pupok.</b>\nПопробуйте ещё раз.",
            parse_mode="HTML",
        )
        return NICKNAME

    context.user_data["nickname"] = text
    await update.message.reply_text(
        step_header(5) + f"<b>Отправьте скриншот лицензии на оружие.</b>\n\n📎 Пример: {EXAMPLE_LICENSE}",
        parse_mode="HTML",
    )
    schedule_reminder(context, user_id)
    return LICENSE_SCREENSHOT


async def license_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await blocked_guard(update):
        return ConversationHandler.END
    user_id = update.effective_user.id

    if update.message.text == BACK_BUTTON_TEXT:
        await update.message.reply_text(
            step_header(4) + "<b>Введите ваш никнейм строго по форме, например: Tema_Pupok</b>",
            parse_mode="HTML",
        )
        return NICKNAME

    if not update.message.photo:
        await update.message.reply_text(
            step_header(5) + "Нужен именно скриншот (фото). <b>Отправьте скрин лицензии на оружие.</b>",
            parse_mode="HTML",
        )
        return LICENSE_SCREENSHOT

    context.user_data["license_screenshot"] = await save_photo(
        context, update.message.photo[-1], f"{user_id}_license"
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
    cancel_reminder(context, user_id)

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
        reply_markup=ReplyKeyboardRemove(),
    )

    await notify_admin_bot(app_id)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cancel_reminder(context, update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text(
        "Процесс отменён. Начать заново — /start.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# --------------------------------------------------------------------------
# УВЕДОМЛЕНИЕ АДМИН-БОТА О НОВОЙ ЗАЯВКЕ
# --------------------------------------------------------------------------

async def notify_admin_bot(app_id: int):
    """
    Отправляет никнейм и скрины админам через ОТДЕЛЬНЫЙ админ-бот (свой
    токен) — поэтому создаём отдельный Bot() без запуска polling, просто
    чтобы разово отправить сообщения. Скрины идут одной "кучкой"
    (media group), а не по одному подряд.
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
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{app_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{app_id}"),
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
            await admin_bot.send_message(
                chat_id=admin_id, text=f"📋 Заявка №{app_id}\n{app['nickname']}"
            )
            media = []
            opened_files = []
            for path in photo_paths:
                f = open(path, "rb")
                opened_files.append(f)
                media.append(InputMediaPhoto(f))
            try:
                await admin_bot.send_media_group(chat_id=admin_id, media=media)
            finally:
                for f in opened_files:
                    f.close()
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
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, conversation_timeout),
                CallbackQueryHandler(conversation_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=TIMEOUT_HOURS * 3600,
    )

    application.add_handler(conv_handler)

    logger.info("Пользовательский бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
