FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py user_bot.py admin_bot.py start.sh ./
RUN chmod +x start.sh

# База данных должна лежать в примонтированном томе (Azure File Share),
# иначе при перезапуске контейнера все заявки потеряются.
VOLUME ["/app/data"]
ENV DB_PATH="/app/data/voenbilet.db"

# Запускает user_bot.py и admin_bot.py одновременно в ОДНОМ контейнере —
# так дешевле в Azure, чем два отдельных контейнера 24/7.
CMD ["./start.sh"]
