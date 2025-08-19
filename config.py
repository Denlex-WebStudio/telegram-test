import os
from dotenv import load_dotenv, find_dotenv, dotenv_values

# Явно ищем .env, начиная с текущей рабочей директории, чтобы надёжно подхватывать переменные
dotenv_path = os.getenv("DOTENV_PATH") or find_dotenv(usecwd=True)
if dotenv_path:
    # Пытаемся загрузить .env из найденного пути (учитываем возможный BOM)
    load_dotenv(dotenv_path=dotenv_path, encoding="utf-8-sig")
else:
    # Фолбэк на стандартный поиск в случае, если find_dotenv не нашёл файл
    load_dotenv(encoding="utf-8-sig")

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Дополнительный устойчивый фолбэк: вручную парсим .env, если по какой-то причине переменные не подхватились
if not BOT_TOKEN and dotenv_path and os.path.exists(dotenv_path):
    try:
        with open(dotenv_path, "r", encoding="utf-8-sig") as f:
            for raw_line in f.readlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().lstrip("\ufeff")
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
        BOT_TOKEN = os.getenv("BOT_TOKEN")
    except Exception:
        # Тихо игнорируем — основной путь загрузки уже был попытался
        pass

# Финальный фолбэк: используем парсер dotenv_values (без установки переменных окружения)
if not BOT_TOKEN and dotenv_path and os.path.exists(dotenv_path):
    try:
        values = dotenv_values(dotenv_path)
        BOT_TOKEN = values.get("BOT_TOKEN", BOT_TOKEN)
    except Exception:
        pass

# Данные медицинского центра
CLINIC_INFO = {
    "name": "Медицинский центр Здоровье+",
    "address": "г. Москва, ул. Медицинская, д. 15",
    "phone": "+7 (495) 123-45-67",
    "website": "https://zdorovie-plus.ru",
    "working_hours": "Пн-Пт: 8:00-20:00\nСб-Вс: 9:00-18:00",
    "map_url": "https://maps.google.com/?q=Москва,ул.Медицинская,д.15",
    # Доп. сведения
    "email": "info@zdorovie-plus.ru",
    "description": (
        "Современный многопрофильный центр, где сочетаются опытные специалисты, "
        "современное оборудование и индивидуальный подход. Мы проводим диагностику, "
        "лечение и профилактику по ключевым направлениям: терапия, кардиология, "
        "неврология, стоматология и др. Заботимся о комфортной и безопасной среде "
        "для пациентов любого возраста."
    )
}

# Специализации врачей
SPECIALIZATIONS = [
    "Терапевт",
    "Стоматолог", 
    "Кардиолог",
    "Невролог",
    "Офтальмолог",
    "Ортопед",
    "Гинеколог",
    "Уролог"
]

# Врачи (пример данных)
DOCTORS = {
    "Терапевт": [
        {
            "name": "Иванов Иван Иванович",
            "experience": "15 лет",
            "photo": "👨‍⚕️",
            "description": "Врач-терапевт высшей категории"
        },
        {
            "name": "Петрова Анна Сергеевна", 
            "experience": "12 лет",
            "photo": "👩‍⚕️",
            "description": "Врач-терапевт первой категории"
        }
    ],
    "Стоматолог": [
        {
            "name": "Сидоров Петр Александрович",
            "experience": "20 лет", 
            "photo": "👨‍⚕️",
            "description": "Врач-стоматолог высшей категории"
        }
    ],
    "Кардиолог": [
        {
            "name": "Козлова Елена Владимировна",
            "experience": "18 лет",
            "photo": "👩‍⚕️", 
            "description": "Врач-кардиолог высшей категории"
        }
    ]
}

# Время приема (пример)
AVAILABLE_TIMES = [
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
    "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
    "18:00", "18:30", "19:00", "19:30"
]

# ID администратора для уведомлений
ADMIN_ID = None  # Будет установлен при первом запуске

# Настройки Google Sheets
# GOOGLE_SHEETS_ID - ID таблицы Google Sheets
# GOOGLE_SERVICE_ACCOUNT_JSON - JSON ключ сервисного аккаунта в одну строку (рекомендуется)
# GOOGLE_SERVICE_ACCOUNT_JSON - путь к JSON файлу сервисного аккаунта (для локальной разработки)
