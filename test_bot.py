#!/usr/bin/env python3
"""
Тестовый файл для проверки основных функций бота
"""

import asyncio
from config import CLINIC_INFO, SPECIALIZATIONS, DOCTORS, AVAILABLE_TIMES
from excel_manager import ExcelManager

def test_config():
    """Тестирование конфигурации"""
    print("=== Тестирование конфигурации ===")
    print(f"Название клиники: {CLINIC_INFO['name']}")
    print(f"Адрес: {CLINIC_INFO['address']}")
    print(f"Телефон: {CLINIC_INFO['phone']}")
    print(f"Сайт: {CLINIC_INFO['website']}")
    print(f"Часы работы:\n{CLINIC_INFO['working_hours']}")
    print()

def test_specializations():
    """Тестирование специализаций"""
    print("=== Специализации врачей ===")
    for i, spec in enumerate(SPECIALIZATIONS, 1):
        print(f"{i}. {spec}")
    print()

def test_doctors():
    """Тестирование данных о врачах"""
    print("=== Врачи по специализациям ===")
    for specialization, doctors in DOCTORS.items():
        print(f"\n{specialization}:")
        for doctor in doctors:
            print(f"  {doctor['photo']} {doctor['name']}")
            print(f"    Стаж: {doctor['experience']}")
            print(f"    {doctor['description']}")
    print()

def test_available_times():
    """Тестирование доступного времени"""
    print("=== Доступное время приема ===")
    for i, time in enumerate(AVAILABLE_TIMES, 1):
        print(f"{i:2d}. {time}", end="  ")
        if i % 4 == 0:
            print()
    print("\n")

def test_excel_manager():
    """Тестирование Excel Manager"""
    print("=== Тестирование Excel ===")
    try:
        excel_manager = ExcelManager()
        print("✅ Excel Manager инициализирован успешно")
        # Пробуем добавить тестовую запись (в память)
        ok = excel_manager.add_subscriber("test_user", "Test User")
        print(f"Добавление тестового подписчика: {'OK' if ok else 'FAIL'}")
    except Exception as e:
        print(f"❌ Ошибка при инициализации Excel: {e}")
    print()

def test_menu_structure():
    """Тестирование структуры меню"""
    print("=== Структура меню бота ===")
    menu_items = [
        "📅 Записаться на приём",
        "👨‍⚕️ Наши врачи", 
        "ℹ️ О клинике",
        "💬 Онлайн-консультация",
        "⭐ Отзывы",
        "🔔 Новости и акции"
    ]
    
    for i, item in enumerate(menu_items, 1):
        print(f"{i}. {item}")
    print()

def test_appointment_flow():
    """Тестирование процесса записи на прием"""
    print("=== Процесс записи на прием ===")
    print("1. Выбор специализации")
    for spec in SPECIALIZATIONS[:3]:  # Показываем первые 3
        print(f"   - {spec}")
    
    print("\n2. Выбор врача")
    if "Терапевт" in DOCTORS:
        for doctor in DOCTORS["Терапевт"]:
            print(f"   - {doctor['name']}")
    
    print("\n3. Выбор даты")
    print("   - Будние дни на ближайшие 2 недели")
    
    print("\n4. Выбор времени")
    for time in AVAILABLE_TIMES[:6]:  # Показываем первые 6
        print(f"   - {time}")
    
    print("\n5. Ввод данных пациента")
    print("   - ФИО")
    print("   - Телефон")
    print()

def main():
    """Основная функция тестирования"""
    print("🏥 Тестирование телеграм бота медицинского центра\n")
    
    test_config()
    test_specializations()
    test_doctors()
    test_available_times()
    test_excel_manager()
    test_menu_structure()
    test_appointment_flow()
    
    print("✅ Все тесты завершены!")
    print("\nДля запуска бота выполните: python bot.py")

if __name__ == "__main__":
    main()
