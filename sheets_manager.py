import os
import json
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
import asyncio
import logging

try:
    import gspread
    from gspread import Spreadsheet, Worksheet
    from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound
    from google.oauth2.service_account import Credentials
    from google.auth.exceptions import DefaultCredentialsError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    gspread = None
    Spreadsheet = None
    Worksheet = None
    Credentials = None
    DefaultCredentialsError = None

logger = logging.getLogger(__name__)

# Требуемые области доступа для работы с Google Sheets / Drive
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class GoogleSheetsManager:
    """Менеджер для работы с Google Sheets"""
    
    def __init__(self):
        self.spreadsheet = None
        self.client = None
        self.sheets = {}
        self.last_sync = {}
        self.sync_interval = 2  # секунды между синхронизациями
        
        # Инициализация Google Sheets
        if self._init_google_sheets():
            logger.info("Google Sheets инициализирован успешно")
        else:
            logger.error("Google Sheets недоступен. Проверьте переменные окружения и учетные данные.")
            self.spreadsheet = None
    
    def _init_google_sheets(self) -> bool:
        """Инициализация подключения к Google Sheets"""
        if not GOOGLE_AVAILABLE:
            logger.error("gspread/Google SDK не установлены (GOOGLE_AVAILABLE=False)")
            return False
            
        try:
            # Получаем ID таблицы из переменных окружения
            spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID")
            if not spreadsheet_id:
                logger.error("GOOGLE_SHEETS_ID не установлен")
                return False
            
            # Получаем учетные данные
            credentials = self._get_credentials()
            if not credentials:
                logger.error("Учетные данные Google не получены (credentials=None)")
                return False
            
            # Создаем клиент
            logger.info("Авторизация gspread...")
            self.client = gspread.authorize(credentials)
            
            # Открываем таблицу
            logger.info(f"Открытие таблицы по ключу: {spreadsheet_id}")
            self.spreadsheet = self.client.open_by_key(spreadsheet_id)
            
            # Инициализируем листы
            self._init_sheets()
            
            return True
            
        except Exception as e:
            logger.exception(f"Ошибка инициализации Google Sheets: {e!r}")
            return False
    
    def _get_credentials(self) -> Optional[Credentials]:
        """Получение учетных данных для Google Sheets"""
        try:
            # Вариант 1: JSON ключ в переменной окружения
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if service_account_json:
                try:
                    # Парсим JSON из строки
                    service_account_info = json.loads(service_account_json)
                    logger.info("Загрузка учетных данных из GOOGLE_SERVICE_ACCOUNT_JSON")
                    creds = Credentials.from_service_account_info(service_account_info, scopes=GOOGLE_SCOPES)
                    return creds
                except json.JSONDecodeError:
                    logger.error("Неверный формат GOOGLE_SERVICE_ACCOUNT_JSON")
                    return None
            
            # Вариант 2: Путь к JSON файлу
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if credentials_path and os.path.exists(credentials_path):
                logger.info(f"Загрузка учетных данных из файла: {credentials_path}")
                creds = Credentials.from_service_account_file(credentials_path, scopes=GOOGLE_SCOPES)
                return creds
            elif credentials_path:
                logger.error(f"GOOGLE_APPLICATION_CREDENTIALS указывает на несуществующий файл: {credentials_path}")
                return None

            # Вариант 3: Автоматическое определение (для локальной разработки)
            try:
                logger.info("Загрузка учетных данных из service-account.json в корне проекта")
                creds = Credentials.from_service_account_file("service-account.json", scopes=GOOGLE_SCOPES)
                return creds
            except FileNotFoundError:
                logger.error("Файл service-account.json не найден в корне проекта")
                pass
            
            logger.warning("Не удалось получить учетные данные Google")
            return None
            
        except Exception as e:
            logger.exception(f"Ошибка получения учетных данных: {e!r}")
            return None
    
    def _init_sheets(self):
        """Инициализация листов таблицы"""
        if not self.spreadsheet:
            return
            
        sheet_names = [
            'Записи на прием',
            'Отзывы', 
            'Онлайн консультации',
            'Подписчики'
        ]
        
        for sheet_name in sheet_names:
            try:
                # Пытаемся получить существующий лист
                sheet = self.spreadsheet.worksheet(sheet_name)
                self.sheets[sheet_name] = sheet
                logger.info(f"Лист '{sheet_name}' загружен")
            except WorksheetNotFound:
                # Создаем новый лист
                try:
                    sheet = self.spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
                    self.sheets[sheet_name] = sheet
                    self._setup_sheet_headers(sheet_name)
                    logger.info(f"Лист '{sheet_name}' создан")
                except Exception as e:
                    logger.error(f"Ошибка создания листа '{sheet_name}': {e}")
    
    def _setup_sheet_headers(self, sheet_name: str):
        """Установка заголовков для листа"""
        if not self.spreadsheet or sheet_name not in self.sheets:
            return
            
        sheet = self.sheets[sheet_name]
        
        headers_map = {
            'Записи на прием': [
                'Дата записи', 'Время', 'ФИО пациента', 'Телефон', 
                'Врач', 'Специализация', 'Статус', 'ID пользователя', 'Дата создания'
            ],
            'Отзывы': [
                'Дата', 'ФИО', 'Оценка', 'Отзыв', 'ID пользователя', 'Статус'
            ],
            'Онлайн консультации': [
                'Дата', 'Вопрос', 'ID пользователя', 'Статус', 'Ответ'
            ],
            'Подписчики': [
                'ID пользователя', 'Имя', 'Дата подписки'
            ]
        }
        
        headers = headers_map.get(sheet_name, [])
        if headers:
            try:
                # Очищаем лист и добавляем заголовки
                sheet.clear()
                sheet.append_row(headers)
                
                # Форматируем заголовки (жирный шрифт)
                sheet.format('A1:Z1', {
                    'textFormat': {'bold': True},
                    'backgroundColor': {'red': 0.8, 'green': 0.8, 'blue': 0.8}
                })
                
                logger.info(f"Заголовки для листа '{sheet_name}' установлены")
            except Exception as e:
                logger.error(f"Ошибка установки заголовков для '{sheet_name}': {e}")
    
    def _get_sheet(self, sheet_name: str) -> Optional[Worksheet]:
        """Получение листа по имени"""
        if not self.spreadsheet:
            return None
        return self.sheets.get(sheet_name)
    
    def _sync_sheet(self, sheet_name: str):
        """Синхронизация листа с Google Sheets"""
        if not self.spreadsheet:
            return
            
        try:
            sheet = self._get_sheet(sheet_name)
            if sheet:
                # Обновляем данные листа
                sheet.update('A1', sheet.get_all_values())
                self.last_sync[sheet_name] = datetime.now()
        except Exception as e:
            logger.error(f"Ошибка синхронизации листа '{sheet_name}': {e}")
    
    def add_appointment(self, date: str, time: str, patient_name: str, phone: str, 
                       doctor: str, specialization: str, user_id: int) -> bool:
        """Добавление записи на прием"""
        try:
            sheet = self._get_sheet('Записи на прием')
            if not sheet:
                return False
            
            # Проверяем на дубликаты
            existing_data = sheet.get_all_values()
            for row in existing_data[1:]:  # Пропускаем заголовки
                if (len(row) >= 8 and 
                    str(row[7]) == str(user_id) and  # ID пользователя
                    str(row[0]) == str(date) and      # Дата
                    str(row[1]) == str(time) and      # Время
                    str(row[4]) == str(doctor)):      # Врач
                    # Обновляем существующую запись
                    row[6] = 'Обновлена'  # Статус
                    row[8] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Дата создания
                    sheet.update(f'A{existing_data.index(row) + 1}:I{existing_data.index(row) + 1}', [row])
                    logger.info(f"Запись обновлена для пользователя {user_id}")
                    return True
            
            # Добавляем новую запись
            new_row = [
                date,
                time,
                patient_name,
                phone,
                doctor,
                specialization,
                'Новая',
                str(user_id),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
            
            sheet.append_row(new_row)
            logger.info(f"Запись добавлена для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления записи: {e}")
            return False
    
    def add_review(self, patient_name: str, rating: int, review_text: str, user_id: int) -> bool:
        """Добавление отзыва"""
        try:
            sheet = self._get_sheet('Отзывы')
            if not sheet:
                return False
            
            new_row = [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                patient_name,
                rating,
                review_text,
                str(user_id),
                'Новый'
            ]
            
            sheet.append_row(new_row)
            logger.info(f"Отзыв добавлен для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления отзыва: {e}")
            return False
    
    def add_consultation(self, question: str, user_id: int) -> bool:
        """Добавление онлайн консультации"""
        try:
            sheet = self._get_sheet('Онлайн консультации')
            if not sheet:
                return False
            
            new_row = [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                question,
                str(user_id),
                'Новая',
                ''
            ]
            
            sheet.append_row(new_row)
            logger.info(f"Консультация добавлена для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления консультации: {e}")
            return False
    
    def add_subscriber(self, user_id: int, user_name: str) -> bool:
        """Добавление подписчика"""
        try:
            sheet = self._get_sheet('Подписчики')
            if not sheet:
                return False
            
            # Проверяем, не подписан ли уже пользователь
            existing_data = sheet.get_all_values()
            for row in existing_data[1:]:  # Пропускаем заголовки
                if len(row) >= 1 and str(row[0]) == str(user_id):
                    logger.info(f"Пользователь {user_id} уже подписан")
                    return True
            
            new_row = [
                str(user_id),
                user_name,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
            
            sheet.append_row(new_row)
            logger.info(f"Подписчик добавлен: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления подписчика: {e}")
            return False
    
    def get_appointments(self) -> List[List]:
        """Получение всех записей на прием"""
        try:
            sheet = self._get_sheet('Записи на прием')
            if not sheet:
                return []
            
            data = sheet.get_all_values()
            if len(data) <= 1:  # Только заголовки
                return []
            
            return data[1:]  # Возвращаем данные без заголовков
            
        except Exception as e:
            logger.error(f"Ошибка получения записей: {e}")
            return []
    
    def get_reviews(self) -> List[List]:
        """Получение всех отзывов"""
        try:
            sheet = self._get_sheet('Отзывы')
            if not sheet:
                return []
            
            data = sheet.get_all_values()
            if len(data) <= 1:  # Только заголовки
                return []
            
            return data[1:]  # Возвращаем данные без заголовков
            
        except Exception as e:
            logger.error(f"Ошибка получения отзывов: {e}")
            return []
    
    def get_subscribers(self) -> List[List]:
        """Получение всех подписчиков"""
        try:
            sheet = self._get_sheet('Подписчики')
            if not sheet:
                return []
            
            data = sheet.get_all_values()
            if len(data) <= 1:  # Только заголовки
                return []
            
            return data[1:]  # Возвращаем данные без заголовков
            
        except Exception as e:
            logger.error(f"Ошибка получения подписчиков: {e}")
            return []
    
    def get_consultations(self) -> List[List]:
        """Получение всех консультаций"""
        try:
            sheet = self._get_sheet('Онлайн консультации')
            if not sheet:
                return []
            
            data = sheet.get_all_values()
            if len(data) <= 1:  # Только заголовки
                return []
            
            return data[1:]  # Возвращаем данные без заголовков
            
        except Exception as e:
            logger.error(f"Ошибка получения консультаций: {e}")
            return []
    
    def get_appointments_by_user(self, user_id: int) -> List[List]:
        """Получение записей на прием для конкретного пользователя"""
        try:
            all_appointments = self.get_appointments()
            user_appointments = []
            
            for appointment in all_appointments:
                if len(appointment) >= 8 and str(appointment[7]) == str(user_id):
                    user_appointments.append(appointment)
            
            # Сортируем по дате создания (колонка 8)
            user_appointments.sort(key=lambda x: x[8] if len(x) > 8 else '', reverse=True)
            
            return user_appointments
            
        except Exception as e:
            logger.error(f"Ошибка получения записей пользователя: {e}")
            return []
    
    def get_booked_times(self, doctor_name: str, date: str) -> set:
        """Получение занятых слотов времени для врача на конкретную дату"""
        try:
            all_appointments = self.get_appointments()
            booked_times = set()
            
            for appointment in all_appointments:
                if (len(appointment) >= 6 and 
                    str(appointment[4]) == str(doctor_name) and  # Врач
                    str(appointment[0]) == str(date) and        # Дата
                    str(appointment[6]).lower() not in ['отменена', 'отменён', 'cancelled', 'canceled']):  # Статус
                    booked_times.add(str(appointment[1]))  # Время
            
            return booked_times
            
        except Exception as e:
            logger.error(f"Ошибка получения занятых слотов: {e}")
            return set()
    
    def delete_appointment(self, user_id: int, date: str, time: str, doctor: str, created_at: str) -> bool:
        """Удаление записи на прием"""
        try:
            sheet = self._get_sheet('Записи на прием')
            if not sheet:
                return False
            
            data = sheet.get_all_values()
            row_to_delete = None
            
            # Ищем строку для удаления
            for i, row in enumerate(data[1:], start=2):  # Пропускаем заголовки
                if (len(row) >= 9 and
                    str(row[7]) == str(user_id) and      # ID пользователя
                    str(row[0]) == str(date) and          # Дата
                    str(row[1]) == str(time) and          # Время
                    str(row[4]) == str(doctor) and        # Врач
                    str(row[8]) == str(created_at)):      # Дата создания
                    row_to_delete = i
                    break
            
            if row_to_delete:
                # Удаляем строку
                sheet.delete_rows(row_to_delete)
                logger.info(f"Запись удалена для пользователя {user_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка удаления записи: {e}")
            return False
    
    def update_appointment_status(self, row_index: int, new_status: str) -> bool:
        """Обновление статуса записи на прием"""
        try:
            sheet = self._get_sheet('Записи на прием')
            if not sheet:
                return False
            
            # Обновляем статус (колонка G, индекс 6)
            sheet.update_cell(row_index + 1, 7, new_status)  # +1 так как row_index начинается с 0
            logger.info(f"Статус записи обновлен на {new_status}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка обновления статуса записи: {e}")
            return False
    
    def update_review_status(self, row_index: int, new_status: str) -> bool:
        """Обновление статуса отзыва"""
        try:
            sheet = self._get_sheet('Отзывы')
            if not sheet:
                return False
            
            # Обновляем статус (колонка F, индекс 5)
            sheet.update_cell(row_index + 1, 6, new_status)  # +1 так как row_index начинается с 0
            logger.info(f"Статус отзыва обновлен на {new_status}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка обновления статуса отзыва: {e}")
            return False
    
    def get_spreadsheet_url(self) -> Optional[str]:
        """Получение URL таблицы"""
        if self.spreadsheet:
            return self.spreadsheet.url
        return None
    
    def is_available(self) -> bool:
        """Проверка доступности Google Sheets"""
        return self.spreadsheet is not None
    
    def flush_pending_ops(self) -> bool:
        """Совместимость с Excel Manager - нет необходимости для Google Sheets"""
        return True
