# 🚀 Быстрый запуск Telegram бота

## Настройка Google Sheets ⭐

### 1. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 2. Создание .env файла
```env
BOT_TOKEN=ваш_токен_бота
GOOGLE_SHEETS_ID=ID_вашей_таблицы
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

### 3. Запуск
```bash
python bot.py
```

**Подробная настройка Google Sheets**: [GOOGLE_SHEETS_SETUP.md](GOOGLE_SHEETS_SETUP.md)

---

## 🧪 Тестирование

Проверьте работу системы:
```bash
python test_google_sheets.py
```

---

## 📊 Что получите

- ✅ Автоматическое создание таблиц Google Sheets
- ✅ Синхронизация в реальном времени
- ✅ Доступ из любого места через веб-интерфейс
- ✅ Все функции бота работают с Google Sheets

---

## 🆘 Проблемы?

1. **Google Sheets не работает** → проверьте настройки сервисного аккаунта
2. **Ошибки импорта** → `pip install -r requirements.txt`
3. **Не создается токен** → [@BotFather](https://t.me/botfather) в Telegram
