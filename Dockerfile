FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py user_bot.py admin_bot.py ./

# База данных должна лежать в примонтированном томе (Azure File Share),
# иначе при перезапуске контейнера все заявки потеряются.
VOLUME ["/app/data"]
ENV DB_PATH="/app/data/voenbilet.db"

# По умолчанию запускается пользовательский бот.
# Для админ-бота команда переопределяется при создании контейнера:
#   --command-line "python admin_bot.py"
CMD ["python", "user_bot.py"]
