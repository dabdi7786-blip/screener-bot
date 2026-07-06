#!/bin/bash
# Добавляет cron-задачу: запуск скринера пн-пт в 08:00

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/venv/bin/python"
SCRIPT="$SCRIPT_DIR/screener_bot.py"
LOG="$SCRIPT_DIR/screener.log"

CRON_LINE="0 8 * * 1-5 cd \"$SCRIPT_DIR\" && $PYTHON $SCRIPT >> $LOG 2>&1"

# Добавить, если ещё не добавлено
(crontab -l 2>/dev/null | grep -F "screener_bot.py" > /dev/null) && {
    echo "Cron уже настроен."
    crontab -l | grep screener_bot
    exit 0
}

(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
echo "✅ Cron добавлен:"
echo "   $CRON_LINE"
echo ""
echo "Проверить: crontab -l"
echo "Логи:      tail -f $LOG"
