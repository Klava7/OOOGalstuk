from flask import Flask, request
import requests
from telegram import (
    Bot, Update,
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Dispatcher, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, InlineQueryHandler
)
from datetime import datetime
import os, uuid, re

# ---------------- Настройки ----------------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Не найден BOT_TOKEN в переменных окружения!")

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=1, use_context=True)

GROUPS = {
    "КББО-12-24": {"desc": "У нас нет рассписания, пока смотрим ваше", "thumb": "https://i.pinimg.com/736x/27/cb/70/27cb70c5b0989fb48d1d06bc32143239.jpg"}
}

chat_days = {}
chat_groups = {}

# ---------------- Утилиты ----------------
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# ---------------- Функции ----------------
def get_group_schedule(group: str):
    url = f"https://rtu-mirea-mobile.herokuapp.com/schedule/{group}/full_schedule"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print(f"Ошибка при запросе расписания: {e}")
        return None

def format_schedule_for_day(schedule_json, day_index: int, markdown=False):
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
    if day_index < 0 or day_index >= len(days):
        return "День не найден"

    day_name = days[day_index]
    text = f"*{day_name}*\n\n" if markdown else f"{day_name}\n\n"

    day_schedule = schedule_json.get("days", {}).get(day_name.lower(), [])
    if not day_schedule:
        return text + ("_Пар нет_" if markdown else "Пар нет")

    for lesson in day_schedule:
        line = f"{lesson['time']}: {lesson['name']} ({lesson['room']})\n"
        text += line

    return text

def day_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="prev_day"),
         InlineKeyboardButton("Вперёд ➡️", callback_data="next_day")]
    ])

# ---------------- Обработчики ----------------
def start(update, context):
    update.message.reply_text(
        "Привет! Отправь сообщение вида '@MIREARTU_bot группа', чтобы получить расписание, "
        "или используй inline поиск (в любом чате набери @MIREARTU_bot и выбери группу)."
    )

def mention_handler(update, context):
    text = update.message.text
    chat_id = update.message.chat_id

    parts = text.split()
    if len(parts) < 2:
        update.message.reply_text("Укажи группу после упоминания бота.")
        return
    group = parts[1].strip().upper()

    if group not in GROUPS:
        update.message.reply_text("Группа не найдена.")
        return

    schedule = get_group_schedule(group)
    if not schedule:
        update.message.reply_text("Ошибка: не удалось получить расписание (API вернуло ошибку).")
        return

    today_index = datetime.today().weekday()
    if today_index >= 6:
        today_index = 0

    chat_days[chat_id] = today_index
    chat_groups[chat_id] = group

    text_message = format_schedule_for_day(schedule, today_index, markdown=True)
    update.message.reply_text(
        text_message, reply_markup=day_buttons(), parse_mode="Markdown"
    )

def button_handler(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id

    if chat_id not in chat_days or chat_id not in chat_groups:
        query.answer("Сначала отправьте группу.")
        return

    if query.data == "next_day":
        chat_days[chat_id] = (chat_days[chat_id] + 1) % 6
    elif query.data == "prev_day":
        chat_days[chat_id] = (chat_days[chat_id] - 1) % 6

    group = chat_groups[chat_id]
    schedule = get_group_schedule(group)
    if not schedule:
        query.answer("Ошибка API: не удалось получить расписание.")
        return

    text_message = format_schedule_for_day(schedule, chat_days[chat_id], markdown=True)
    query.edit_message_text(
        text_message, reply_markup=day_buttons(), parse_mode="Markdown"
    )
    query.answer()

def inline_query_handler(update, context):
    query_text = update.inline_query.query.strip().upper()

    results = []
    for group, info in GROUPS.items():
        if query_text and query_text not in group:
            continue

        schedule = get_group_schedule(group)
        if not schedule:
            text_message = f"Ошибка: не удалось загрузить расписание для {group}."
        else:
            today_index = datetime.today().weekday()
            if today_index >= 6:
                today_index = 0
            text_message = format_schedule_for_day(schedule, today_index)

        safe_text = escape_markdown(text_message)

        results.append(
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=group,
                description=info["desc"],
                thumb_url=info["thumb"],
                input_message_content=InputTextMessageContent(
                    safe_text,
                    parse_mode="MarkdownV2"
                )
            )
        )

    update.inline_query.answer(results, cache_time=0)

# ---------------- Подключение обработчиков ----------------
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, mention_handler))
dispatcher.add_handler(CallbackQueryHandler(button_handler))
dispatcher.add_handler(InlineQueryHandler(inline_query_handler))

# ---------------- Flask webhook ----------------
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
