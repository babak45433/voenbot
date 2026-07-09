#!/bin/bash
# Запускает user_bot.py и admin_bot.py как два фоновых процесса в одном
# контейнере. Если один из них упадёт — весь контейнер завершится с ошибкой,
# и Azure (restart-policy Always) перезапустит контейнер целиком — оба бота
# поднимутся заново.

set -e

python user_bot.py &
USER_PID=$!

python admin_bot.py &
ADMIN_PID=$!

# Ждём, пока завершится любой из двух процессов, и выходим с его кодом
wait -n "$USER_PID" "$ADMIN_PID"
exit $?
