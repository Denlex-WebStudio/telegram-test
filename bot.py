import logging
import json
import asyncio
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
from config import BOT_TOKEN, CLINIC_INFO, SPECIALIZATIONS, DOCTORS, AVAILABLE_TIMES, ADMIN_ID
from excel_manager import ExcelManager
try:
    from sheets_manager import SheetsManager
except Exception:
    SheetsManager = None

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
CHOOSING_SPECIALIZATION, CHOOSING_DOCTOR, CHOOSING_DATE, CHOOSING_TIME, ENTERING_NAME, ENTERING_PHONE = range(6)
REVIEW_RATING, REVIEW_TEXT = range(2)

# Инициализация хранилища: Google Sheets при наличии конфигурации, иначе Excel
if SheetsManager is not None and os.getenv('GOOGLE_SHEETS_ID'):
    excel_manager = SheetsManager()
else:
    excel_manager = ExcelManager()

# Словарь для хранения данных пользователей
user_data = {}
excel_sync_started = False

# Лёгкая синхронизация Excel без сторонних библиотек (через встроенный планировщик)
known_active_appointment_keys = set()
known_active_review_keys = set()

# Кеш и сведения о последнем сообщении «Мои записи» для автообновления
my_appts_cache = {}
my_appts_view = {}

def build_my_appts_text_and_keyboard(user_id: int):
    appointments = excel_manager.get_appointments_by_user(user_id)
    keyboard_rows = []
    if not appointments:
        text = "У вас пока нет записей."
        my_appts_cache[user_id] = []
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]])

    # Сортировка по дате создания по убыванию (колонка 9)
    try:
        appointments.sort(key=lambda r: str(r[8] or ''), reverse=True)
    except Exception:
        pass

    my_appts_cache[user_id] = appointments

    text = "🗂 Ваши записи:\n\n"
    for i, a in enumerate(appointments, start=1):
        date, time, name, phone, doctor, specialization, status, uid, created_at = a
        text += f"{i}. 📅 {date} {time}\n"
        text += f"   👨‍⚕️ {doctor} ({specialization})\n"
        text += f"   👤 {name}\n"
        text += f"   📞 {phone}\n"
        text += f"   🔖 Статус: {status}\n"
        text += f"   🕒 Создано: {created_at}\n"
        # Проверка доступности отмены (>24ч и не отменена)
        can_cancel = False
        try:
            from datetime import datetime as dt
            if isinstance(date, str):
                appt_date = dt.strptime(date, "%d.%m.%Y")
            else:
                appt_date = dt.combine(date, dt.min.time()) if hasattr(date, 'year') else None
            appt_dt = None
            if appt_date and isinstance(time, str):
                h, m = time.split(":")
                appt_dt = appt_date.replace(hour=int(h), minute=int(m))
            if appt_dt and (appt_dt - dt.now()).total_seconds() > 24*3600 and str(status).lower() not in ["отменена", "cancelled"]:
                can_cancel = True
        except Exception:
            pass
        if can_cancel:
            keyboard_rows.append([InlineKeyboardButton(f"❌ Отменить #{i}", callback_data=f"cancel_appt_{i}")])
        text += "\n"

    if not keyboard_rows:
        text += "\nОтменить запись можно только более чем за 24 часа до приёма."

    reply_markup = InlineKeyboardMarkup(keyboard_rows + [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]])
    return text, reply_markup

async def refresh_my_appts_message_for_user(application: Application, user_id: int):
    view = my_appts_view.get(user_id)
    if not view:
        return
    chat_id, message_id = view
    try:
        text, reply_markup = build_my_appts_text_and_keyboard(user_id)
        await application.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup
        )
    except Exception:
        pass

def _normalize_date_str(value):
    try:
        if isinstance(value, str):
            return value
        from datetime import datetime as dt
        return value.strftime("%d.%m.%Y")
    except Exception:
        return str(value)

def _normalize_created_str(value):
    try:
        if isinstance(value, str):
            return value
        from datetime import datetime as dt
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)

def build_active_appointment_keys():
    rows = excel_manager.get_appointments()
    keys = set()
    for row in rows:
        try:
            date, time, _name, _phone, doctor, _spec, status, user_id, created_at = row
            status_str = str(status).lower()
            if status_str in ["отменена", "отменён", "cancelled", "canceled", "cancel"]:
                continue
            keys.add((
                str(user_id),
                _normalize_date_str(date),
                str(time),
                str(doctor),
                _normalize_created_str(created_at),
            ))
        except Exception:
            continue
    return keys

def build_active_review_keys():
    rows = excel_manager.get_reviews()
    keys = set()
    for row in rows:
        try:
            date, name, rating, review_text, user_id, status = row
            status_str = str(status).lower()
            if status_str in ["удален", "удалён", "скрыт", "отклонен", "отклонён", "deleted", "hidden", "rejected"]:
                continue
            keys.add((
                str(user_id),
                _normalize_date_str(date),
                str(rating),
                str(review_text),
            ))
        except Exception:
            continue
    return keys

async def sync_excel_changes(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодическая сверка Excel: уведомляем пользователя об удалённых/отменённых записях и скрытых/удалённых отзывах."""
    global known_active_appointment_keys, known_active_review_keys
    try:
        current_appts = build_active_appointment_keys()
        current_reviews = build_active_review_keys()

        # Инициализация без уведомлений
        if not known_active_appointment_keys and not known_active_review_keys:
            known_active_appointment_keys = current_appts
            known_active_review_keys = current_reviews
            return

        removed_appts = known_active_appointment_keys - current_appts
        removed_reviews = known_active_review_keys - current_reviews

        for user_id_str, date_str, time_str, doctor_str, _created_str in removed_appts:
            try:
                await context.application.bot.send_message(
                    chat_id=int(user_id_str),
                    text=(
                        f"Вашу запись на {date_str} {time_str} к {doctor_str} отменили администраторы или она была удалена.\n"
                        f"При необходимости запишитесь заново."
                    ),
                )
            except Exception:
                pass

        for user_id_str, date_str, rating_str, review_text in removed_reviews:
            try:
                preview = (review_text[:120] + '…') if len(review_text) > 120 else review_text
                await context.application.bot.send_message(
                    chat_id=int(user_id_str),
                    text=(
                        f"Ваш отзыв от {date_str} (оценка {rating_str}) был удалён/скрыт администратором.\n"
                        f"Текст: {preview}"
                    ),
                )
            except Exception:
                pass

        known_active_appointment_keys = current_appts
        known_active_review_keys = current_reviews
    except Exception:
        # Не падаем, если файл временно занят/нечитаем
        pass

async def background_excel_sync(application: Application) -> None:
    """Фоновая синхронизация без JobQueue: цикл с asyncio.sleep."""
    global known_active_appointment_keys, known_active_review_keys
    # Инициализируем снимок
    try:
        known_active_appointment_keys = build_active_appointment_keys()
        known_active_review_keys = build_active_review_keys()
    except Exception:
        known_active_appointment_keys = set()
        known_active_review_keys = set()
    while True:
        try:
            # Пробуем применить отложенные операции, если файл разблокирован
            try:
                excel_manager.flush_pending_ops()
            except Exception:
                pass
            current_appts = build_active_appointment_keys()
            current_reviews = build_active_review_keys()
            removed_appts = known_active_appointment_keys - current_appts
            removed_reviews = known_active_review_keys - current_reviews
            for user_id_str, date_str, time_str, doctor_str, _created_str in removed_appts:
                try:
                    await application.bot.send_message(
                        chat_id=int(user_id_str),
                        text=(
                            f"Вашу запись на {date_str} {time_str} к {doctor_str} отменили администраторы или она была удалена.\n"
                            f"При необходимости запишитесь заново."
                        ),
                    )
                    await refresh_my_appts_message_for_user(application, int(user_id_str))
                except Exception:
                    pass
            for user_id_str, date_str, rating_str, review_text in removed_reviews:
                try:
                    preview = (review_text[:120] + '…') if len(review_text) > 120 else review_text
                    await application.bot.send_message(
                        chat_id=int(user_id_str),
                        text=(
                            f"Ваш отзыв от {date_str} (оценка {rating_str}) был удалён/скрыт администратором.\n"
                            f"Текст: {preview}"
                        ),
                    )
                except Exception:
                    pass
            known_active_appointment_keys = current_appts
            known_active_review_keys = current_reviews
        except Exception:
            pass
        await asyncio.sleep(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    # Гарантируем запуск фоновой синхронизации после старта (когда уже есть event loop)
    global excel_sync_started
    if not excel_sync_started:
        try:
            context.application.create_task(background_excel_sync(context.application))
            excel_sync_started = True
        except Exception:
            pass
    welcome_text = f"Здравствуйте! Добро пожаловать в {CLINIC_INFO['name']}. Чем могу помочь?"
    
    keyboard = [
        [InlineKeyboardButton("📅 Записаться на приём", callback_data="appointment")],
        [InlineKeyboardButton("🗂 Мои записи", callback_data="my_appointments")],
        [InlineKeyboardButton("👨‍⚕️ Наши врачи", callback_data="doctors")],
        [InlineKeyboardButton("ℹ️ О клинике", callback_data="clinic_info")],
        [InlineKeyboardButton("💬 Онлайн-консультация", callback_data="consultation")],
        [InlineKeyboardButton("⭐ Отзывы", callback_data="reviews")],
        [InlineKeyboardButton("🔔 Новости и акции", callback_data="news")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    # Резервный запуск фоновой синхронизации, если /start не нажимали
    global excel_sync_started
    if not excel_sync_started:
        try:
            context.application.create_task(background_excel_sync(context.application))
            excel_sync_started = True
        except Exception:
            pass
    
    if query.data == "appointment":
        await show_specializations(update, context)
    elif query.data == "my_appointments":
        await show_my_appointments(update, context)
    elif query.data == "doctors":
        await show_doctors(update, context)
    elif query.data == "clinic_info":
        await show_clinic_info(update, context)
    elif query.data == "consultation":
        await start_consultation(update, context)
    elif query.data == "reviews":
        await show_reviews_menu(update, context)
    elif query.data == "news":
        await show_news(update, context)
    elif query.data == "subscribe_news":
        await subscribe_news(update, context)
    elif query.data == "view_reviews":
        await show_reviews(update, context)
    elif query.data.startswith("cancel_appt_"):
        try:
            idx = int(query.data.split("_")[-1])
        except Exception:
            await query.answer("Неверный формат", show_alert=True)
            return
        await cancel_appointment_by_index(update, context, idx)
    elif query.data.startswith("spec_"):
        specialization = query.data[5:]
        await show_doctors_by_specialization(update, context, specialization)
    elif query.data.startswith("doctor_"):
        doctor_info = query.data[7:]
        await show_doctor_details(update, context, doctor_info)
    elif query.data.startswith("date_"):
        date = query.data[5:]
        await show_available_times(update, context, date)
    # обработка выбора времени перенесена в обработчик диалога записи
    elif query.data == "back_to_menu":
        await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню"""
    keyboard = [
        [InlineKeyboardButton("📅 Записаться на приём", callback_data="appointment")],
        [InlineKeyboardButton("🗂 Мои записи", callback_data="my_appointments")],
        [InlineKeyboardButton("👨‍⚕️ Наши врачи", callback_data="doctors")],
        [InlineKeyboardButton("ℹ️ О клинике", callback_data="clinic_info")],
        [InlineKeyboardButton("💬 Онлайн-консультация", callback_data="consultation")],
        [InlineKeyboardButton("⭐ Отзывы", callback_data="reviews")],
        [InlineKeyboardButton("🔔 Новости и акции", callback_data="news")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Выберите нужную опцию:", reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Выберите нужную опцию:", reply_markup=reply_markup)

async def show_specializations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать список специализаций"""
    keyboard = []
    for spec in SPECIALIZATIONS:
        keyboard.append([InlineKeyboardButton(spec, callback_data=f"spec_{spec}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "Выберите специализацию врача:", reply_markup=reply_markup
    )

async def show_doctors_by_specialization(update: Update, context: ContextTypes.DEFAULT_TYPE, specialization: str) -> None:
    """Показать врачей по специализации"""
    doctors = DOCTORS.get(specialization, [])
    
    if not doctors:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="appointment")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            f"К сожалению, врачи специализации '{specialization}' временно недоступны.",
            reply_markup=reply_markup
        )
        return
    
    text = f"Врачи специализации '{specialization}':\n\n"
    keyboard = []
    
    for i, doctor in enumerate(doctors):
        text += f"{doctor['photo']} {doctor['name']}\n"
        text += f"Стаж: {doctor['experience']}\n"
        text += f"{doctor['description']}\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"📅 Записаться к {doctor['name'].split()[0]}", 
            callback_data=f"doctor_{specialization}_{i}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="appointment")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_doctor_details(update: Update, context: ContextTypes.DEFAULT_TYPE, doctor_info: str) -> None:
    """Показать детали врача и даты записи"""
    specialization, doctor_index = doctor_info.split("_")
    doctor_index = int(doctor_index)
    
    doctors = DOCTORS.get(specialization, [])
    if doctor_index >= len(doctors):
        await update.callback_query.edit_message_text("Ошибка: врач не найден")
        return
    
    doctor = doctors[doctor_index]
    
    # Генерируем даты на ближайшие 2 недели
    dates = []
    for i in range(14):
        date = datetime.now() + timedelta(days=i+1)
        if date.weekday() < 5:  # Только будние дни
            dates.append(date.strftime("%d.%m.%Y"))
    
    text = f"Выбран врач: {doctor['name']}\n"
    text += f"Специализация: {specialization}\n"
    text += f"Стаж: {doctor['experience']}\n\n"
    text += "Выберите дату приема:"
    
    keyboard = []
    for i in range(0, len(dates), 3):
        row = []
        for j in range(3):
            if i + j < len(dates):
                row.append(InlineKeyboardButton(dates[i+j], callback_data=f"date_{dates[i+j]}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"spec_{specialization}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Сохраняем данные о выбранном враче
    user_id = update.effective_user.id
    user_data[user_id] = {
        'doctor': doctor,
        'specialization': specialization
    }
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_available_times(update: Update, context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    """Показать доступное время"""
    text = f"Выбрана дата: {date}\n\nВыберите время приема:"
    
    # Фильтруем занятые слоты для выбранного врача
    user_id = update.effective_user.id
    doctor_name = user_data.get(user_id, {}).get('doctor', {}).get('name') if user_id in user_data else None
    booked = set()
    if doctor_name:
        booked = excel_manager.get_booked_times(doctor_name, date)

    available_slots = [t for t in AVAILABLE_TIMES if t not in booked]

    keyboard = []
    for i in range(0, len(available_slots), 3):
        row = []
        for j in range(3):
            if i + j < len(available_slots):
                time = available_slots[i+j]
                row.append(InlineKeyboardButton(time, callback_data=f"time_{time}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="appointment")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Сохраняем выбранную дату
    user_id = update.effective_user.id
    if user_id in user_data:
        user_data[user_id]['date'] = date
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def start_appointment_form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начать заполнение формы записи"""
    user_id = update.effective_user.id
    # Определяем время из callback данных
    callback = update.callback_query
    selected_time = None
    if callback and callback.data and callback.data.startswith("time_"):
        selected_time = callback.data[5:]
    
    if user_id in user_data and selected_time:
        user_data[user_id]['time'] = selected_time
    
    await update.callback_query.edit_message_text(
        "Для завершения записи введите ваше ФИО:"
    )
    return ENTERING_NAME

async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода ФИО"""
    user_id = update.effective_user.id
    if user_id in user_data:
        user_data[user_id]['name'] = update.message.text
    
    await update.message.reply_text("Теперь введите ваш номер телефона:")
    return ENTERING_PHONE

async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода телефона и завершение записи"""
    user_id = update.effective_user.id
    if user_id in user_data:
        user_data[user_id]['phone'] = update.message.text
        
        # Получаем данные записи
        data = user_data[user_id]
        doctor = data['doctor']
        specialization = data['specialization']
        date = data['date']
        time = data['time']
        name = data['name']
        phone = data['phone']
        
        # Сохраняем в Excel файл
        success = excel_manager.add_appointment(
            date, time, name, phone, doctor['name'], specialization, user_id
        )
        
        if success:
            confirmation_text = f"✅ Запись успешно создана!\n\n"
            confirmation_text += f"Врач: {doctor['name']}\n"
            confirmation_text += f"Специализация: {specialization}\n"
            confirmation_text += f"Дата: {date}\n"
            confirmation_text += f"Время: {time}\n"
            confirmation_text += f"ФИО: {name}\n"
            confirmation_text += f"Телефон: {phone}\n\n"
            confirmation_text += "Мы напомним вам за день до приема."
            
            keyboard = [[InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(
                "❌ Произошла ошибка при создании записи. Попробуйте позже."
            )
        
        # Очищаем данные пользователя
        if user_id in user_data:
            del user_data[user_id]
    
    return ConversationHandler.END

async def show_doctors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать всех врачей"""
    text = "Наши врачи:\n\n"
    keyboard = []
    
    for specialization, doctors in DOCTORS.items():
        text += f"🏥 {specialization}:\n"
        for doctor in doctors:
            text += f"  {doctor['photo']} {doctor['name']} - {doctor['experience']}\n"
        text += "\n"
    
    keyboard.append([InlineKeyboardButton("📅 Записаться на приём", callback_data="appointment")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_clinic_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию о клинике"""
    text = f"🏥 {CLINIC_INFO['name']}\n\n"
    if CLINIC_INFO.get('description'):
        text += f"{CLINIC_INFO['description']}\n\n"
    text += f"📍 Адрес: {CLINIC_INFO['address']}\n"
    text += f"⏰ Часы работы:\n{CLINIC_INFO['working_hours']}\n"
    text += f"📞 Телефон: {CLINIC_INFO['phone']}\n"
    if CLINIC_INFO.get('email'):
        text += f"✉️ Email: {CLINIC_INFO['email']}\n"
    text += f"🌐 Сайт: {CLINIC_INFO['website']}"
    
    keyboard = [
        [InlineKeyboardButton("🗺️ Открыть карту", url=CLINIC_INFO['map_url'])],
        [InlineKeyboardButton("🌐 Перейти на сайт", url=CLINIC_INFO['website'])],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        # Если редактирование не удалось (напр., из-за URL-схемы), отправим новое сообщение
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

async def start_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начать онлайн консультацию"""
    text = "💬 Онлайн-консультация\n\n"
    text += "Опишите ваш вопрос, и наш врач свяжется с вами в ближайшее время.\n"
    text += "Вы также можете прикрепить фото или документы."
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    
    # Устанавливаем состояние для ожидания вопроса
    context.user_data['waiting_for_consultation'] = True

async def handle_consultation_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка сообщений для онлайн консультации"""
    if context.user_data.get('waiting_for_consultation'):
        user = update.effective_user
        question = update.message.text
        
        # Сохраняем в Excel файл
        success = excel_manager.add_consultation(question, user.id)
        
        if success:
            await update.message.reply_text(
                "✅ Ваш вопрос отправлен! Врач свяжется с вами в ближайшее время."
            )
        else:
            await update.message.reply_text(
                "❌ Произошла ошибка при отправке вопроса. Попробуйте позже."
            )
        
        # Сбрасываем состояние
        context.user_data['waiting_for_consultation'] = False
        
        # Показываем главное меню
        await show_main_menu(update, context)

async def show_reviews_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать меню отзывов"""
    text = "⭐ Отзывы\n\n"
    text += "Выберите действие:"
    
    keyboard = [
        [InlineKeyboardButton("📝 Оставить отзыв", callback_data="write_review")],
        [InlineKeyboardButton("👀 Посмотреть отзывы", callback_data="view_reviews")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_my_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать записи текущего пользователя"""
    user = update.effective_user
    appointments = excel_manager.get_appointments_by_user(user.id)

    keyboard_rows = []
    if not appointments:
        text = "У вас пока нет записей."
    else:
        text = "🗂 Ваши записи:\n\n"
        # Сортируем по дате создания по убыванию (колонка 9)
        try:
            appointments.sort(key=lambda r: str(r[8] or ''), reverse=True)
        except Exception:
            pass
        context.user_data['my_appts'] = []
        for i, a in enumerate(appointments, start=1):
            date, time, name, phone, doctor, specialization, status, uid, created_at = a
            text += f"{i}. 📅 {date} {time}\n"
            text += f"   👨‍⚕️ {doctor} ({specialization})\n"
            text += f"   👤 {name}\n"
            text += f"   📞 {phone}\n"
            text += f"   🔖 Статус: {status}\n"
            text += f"   🕒 Создано: {created_at}\n"
            # Проверка доступности отмены
            can_cancel = False
            try:
                from datetime import datetime as dt
                if isinstance(date, str):
                    appt_date = dt.strptime(date, "%d.%m.%Y")
                else:
                    appt_date = dt.combine(date, dt.min.time()) if hasattr(date, 'year') else None
                appt_dt = None
                if appt_date and isinstance(time, str):
                    h, m = time.split(":")
                    appt_dt = appt_date.replace(hour=int(h), minute=int(m))
                if appt_dt and (appt_dt - dt.now()).total_seconds() > 24*3600 and str(status).lower() not in ["отменена", "cancelled"]:
                    can_cancel = True
            except Exception:
                pass
            if can_cancel:
                keyboard_rows.append([InlineKeyboardButton(f"❌ Отменить #{i}", callback_data=f"cancel_appt_{i}")])
            text += "\n"
            context.user_data['my_appts'].append(a)
        if not keyboard_rows:
            text += "\nОтменить запись можно только более чем за 24 часа до приёма."

    keyboard = keyboard_rows + [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Сохраняем ссылку на сообщение для автообновления
    sent = await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    try:
        # Учитываем, что edit_message_text возвращает Message в PTB 22.x
        my_appts_view[user.id] = (sent.chat.id, sent.message_id)
    except Exception:
        pass

async def start_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начать процесс написания отзыва"""
    keyboard = []
    for i in range(1, 6):
        stars = "⭐" * i
        keyboard.append([InlineKeyboardButton(f"{stars} ({i})", callback_data=f"rating_{i}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="reviews")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "Оцените нашу клинику от 1 до 5 звезд:", reply_markup=reply_markup
    )
    return REVIEW_RATING

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора рейтинга"""
    query = update.callback_query
    await query.answer()
    
    rating = int(query.data.split("_")[1])
    context.user_data['rating'] = rating
    
    await query.edit_message_text(
        f"Вы поставили {rating} звезд. Теперь напишите ваш отзыв:"
    )
    return REVIEW_TEXT

async def handle_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текста отзыва"""
    user = update.effective_user
    review_text = update.message.text
    rating = context.user_data.get('rating', 5)
    
    # Сохраняем в Excel файл
    success = excel_manager.add_review(
        f"{user.first_name} {user.last_name or ''}".strip(),
        rating,
        review_text,
        user.id
    )
    
    if success:
        await update.message.reply_text(
            "✅ Спасибо за ваш отзыв! Он будет опубликован после модерации."
        )
    else:
        await update.message.reply_text(
            "❌ Произошла ошибка при сохранении отзыва. Попробуйте позже."
        )
    
    # Очищаем данные
    if 'rating' in context.user_data:
        del context.user_data['rating']
    
    # Показываем главное меню
    await show_main_menu(update, context)
    return ConversationHandler.END

async def show_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать существующие отзывы"""
    reviews = excel_manager.get_reviews()
    
    if not reviews:
        text = "Пока нет отзывов. Будьте первым!"
    else:
        text = "📝 Отзывы наших пациентов:\n\n"
        # Показываем все отзывы, включая новые
        for review in reviews:
            date, name, rating, review_text, user_id, status = review
            stars = "⭐" * int(rating)
            text += f"{stars}\n"
            text += f"👤 {name}\n"
            text += f"💬 {review_text}\n"
            text += f"📅 {date}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("📝 Оставить отзыв", callback_data="write_review")],
        [InlineKeyboardButton("🔙 Назад", callback_data="reviews")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать новости и акции"""
    text = "🔔 Новости и акции\n\n"
    text += "🎉 Только в августе! Консультация кардиолога за 500₽ вместо 1000₽\n\n"
    text += "🆕 Новый врач-невролог в нашей клинике\n\n"
    text += "💉 Акция на анализы крови - скидка 20%\n\n"
    text += "Подпишитесь на рассылку, чтобы получать уведомления о новых акциях!"
    
    keyboard = [
        [InlineKeyboardButton("📧 Подписаться на рассылку", callback_data="subscribe_news")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def subscribe_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подписка на новости"""
    user = update.effective_user
    
    # Добавляем в Excel файл
    success = excel_manager.add_subscriber(user.id, f"{user.first_name} {user.last_name or ''}".strip())
    
    if success:
        await update.callback_query.edit_message_text(
            "✅ Вы успешно подписались на рассылку новостей и акций!"
        )
    else:
        await update.callback_query.edit_message_text(
            "❌ Произошла ошибка при подписке. Попробуйте позже."
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена операции"""
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

async def cancel_appointment_by_index(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    """Отменить запись по индексу из контекста, удалить её из Excel"""
    appts = context.user_data.get('my_appts', [])
    if index < 1 or index > len(appts):
        await update.callback_query.answer("Неверный номер записи", show_alert=True)
        return
    date, time, name, phone, doctor, specialization, status, uid, created_at = appts[index - 1]

    # Проверка 24 часов
    from datetime import datetime as dt
    try:
        if isinstance(date, str):
            appt_date = dt.strptime(date, "%d.%m.%Y")
        else:
            appt_date = dt.combine(date, dt.min.time()) if hasattr(date, 'year') else None
        appt_dt = None
        if appt_date and isinstance(time, str):
            h, m = time.split(":")
            appt_dt = appt_date.replace(hour=int(h), minute=int(m))
        if not appt_dt or (appt_dt - dt.now()).total_seconds() <= 24*3600:
            await update.callback_query.answer("Отменить запись можно только более чем за 24 часа до приёма", show_alert=True)
            return
    except Exception:
        await update.callback_query.answer("Не удалось проверить время записи", show_alert=True)
        return

    # Удаляем запись из Excel
    ok = excel_manager.delete_appointment(update.effective_user.id, str(date), str(time), str(doctor), str(created_at))
    if ok:
        await update.callback_query.answer("Запись отменена", show_alert=True)
        # Обновляем список и экран
        await show_my_appointments(update, context)
        # Если пользователь находится на экране «Мои записи», обновим сообщение
        try:
            await refresh_my_appts_message_for_user(context.application, update.effective_user.id)
        except Exception:
            pass
    else:
        await update.callback_query.answer("Ошибка при отмене записи", show_alert=True)

def main() -> None:
    """Запуск бота"""
    # Создаем приложение
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set. Create a .env file with BOT_TOKEN=your_token or set the environment variable."
        )
    application = Application.builder().token(BOT_TOKEN).build()

    # Команда для администратора: отправить текущий Excel-файл
    async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = ADMIN_ID
        if admin_id and str(update.effective_user.id) != str(admin_id):
            await update.message.reply_text("Команда доступна только администратору")
            return
        try:
            # Excel-файл: отправляем документ
            if hasattr(excel_manager, 'filename') and excel_manager.filename and os.path.exists(getattr(excel_manager, 'filename', '')):
                await update.message.reply_document(document=open(excel_manager.filename, 'rb'))
                return
            # Google Sheets: отправляем ссылку на таблицу
            if hasattr(excel_manager, 'spreadsheet'):
                sheet_url = getattr(excel_manager.spreadsheet, 'url', None)
                if not sheet_url and hasattr(excel_manager, 'spreadsheet_id'):
                    sheet_url = f"https://docs.google.com/spreadsheets/d/{excel_manager.spreadsheet_id}"
                if sheet_url:
                    await update.message.reply_text(f"Ссылка на таблицу: {sheet_url}")
                    return
            await update.message.reply_text("Не удалось найти источник данных для экспорта.")
        except Exception as e:
            await update.message.reply_text(f"Не удалось отправить файл: {e}")
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("export", export_excel))
    
    # ConversationHandler для записи на прием
    appointment_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_appointment_form, pattern="^time_")],
        states={
            ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            ENTERING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(appointment_conv_handler)
    
    # ConversationHandler для отзывов
    review_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_review, pattern="^write_review$")],
        states={
            REVIEW_RATING: [CallbackQueryHandler(handle_rating, pattern="^rating_")],
            REVIEW_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_review_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(review_conv_handler)
    
    # Обработчик кнопок (после ConversationHandler, чтобы не перехватывать их события)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик сообщений для консультаций
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_consultation_message))
    
    # Фоновую синхронизацию запускаем при первом пользовательском обновлении (см. start/button_handler)

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
