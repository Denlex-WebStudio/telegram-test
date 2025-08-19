#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы Google Sheets
Запустите: python test_google_sheets.py
"""

import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def test_google_sheets():
    """Тест подключения к Google Sheets"""
    print("🔍 Тестирование Google Sheets...")
    
    # Проверяем переменные окружения
    sheets_id = os.getenv("GOOGLE_SHEETS_ID")
    service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    credentials_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    print(f"📊 GOOGLE_SHEETS_ID: {'✅' if sheets_id else '❌'}")
    print(f"🔑 GOOGLE_SERVICE_ACCOUNT_JSON: {'✅' if service_account else '❌'}")
    print(f"📁 GOOGLE_APPLICATION_CREDENTIALS: {'✅' if credentials_file else '❌'}")
    
    if not sheets_id:
        print("❌ GOOGLE_SHEETS_ID не установлен")
        return False
    
    if not service_account and not credentials_file:
        print("❌ Не настроены учетные данные Google")
        return False
    
    # Пытаемся импортировать и инициализировать Google Sheets
    try:
        from sheets_manager import GoogleSheetsManager
        print("✅ Google Sheets модуль импортирован")
        
        manager = GoogleSheetsManager()
        if manager.is_available():
            print("✅ Google Sheets подключен успешно!")
            print(f"📊 URL таблицы: {manager.get_spreadsheet_url()}")
            return True
        else:
            print("❌ Google Sheets недоступен")
            return False
            
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        print("💡 Установите зависимости: pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
        return False



def main():
    """Основная функция тестирования"""
    print("🚀 Тестирование системы хранения данных Telegram бота")
    print("=" * 60)
    
    # Тестируем Google Sheets
    google_ok = test_google_sheets()
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    print(f"Google Sheets: {'✅' if google_ok else '❌'}")
    
    if google_ok:
        print("\n🎉 Google Sheets настроен и готов к работе!")
        print("💡 Бот будет использовать Google Sheets для хранения данных")
    else:
        print("\n❌ Google Sheets не настроен")
        print("💡 Для настройки Google Sheets см. GOOGLE_SHEETS_SETUP.md")
    
    return google_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
