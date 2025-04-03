# app.py
import logging
import threading
import time

import services
from models import StorageLocation, StockItem
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from config import Config
from services import LogisticsService, ScannersQueue


def create_app():
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    session = Session()

    #test
    locations = session.query(StorageLocation).all()
    for loc in locations:
        print(f"Зона: {loc.sector_name}, Вместимость: {loc.capacity}")

def create_invoice(logistic_service: LogisticsService):
    #формируем список товаров для заказа на получение (id, количество)
    items = [
        (5, 50)
    ]
    sender = "WHAAAAAARUS060ru01100001"  # 24 символа, отправитель - последние 4 цифры - случайные или просто не трогай
    logistic_service.create_invoice_request(items, sender) # вызов функции обработчика (глубже опускаться не надо, достаточно вызывать её и передавать параметры)


def departure_invoice(logistic_service: LogisticsService):
    # формируем список товаров для заказа на отправку (id, количество)
    items = [
        (5, 10)
    ]
    reciver = "WHAAAAAARUS060ru01100001"  # 24 символа, получатель - последние 4 цифры - случайные или просто не трогай
    logistic_service.create_departure_invoice(items, Config.RECIPIENT_WAREHOUSE, reciver) # вызов функции обработчика (глубже опускаться не надо, достаточно вызывать её и передавать параметры)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger('Main')
    stock_monitor = None
    invoice_processor = None

    try:
        invoice_processor = services.InvoiceProcessor()
        threading.Thread(target=invoice_processor.start_processing, daemon=True).start()

        # Инициализация монитора
        stock_monitor = services.StockMonitor()
        stock_monitor.start_monitoring()
        logger.info("Warehouse service started")

        # Основной цикл
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
    finally:
        if stock_monitor:
            stock_monitor.stop_monitoring()
        logger.info("Service stopped")

    # create_app()
    # service = LogisticsService()
    #
    #
    # # # ручные тестовые вызовы
    # # # вызов функции на отправку товара от нас
    # # if input() == 'di':
    #     departure_invoice(service)
    #     exit(201)
    #
    # # вызов функция на получения товара от кого то в этот склад
    # # запрашиваем товар через накладную (создаём накладную через create_invoice)
    # if input() == 'si':
    #     create_invoice(service)
    # # выполняем функцию satisfying_invoices --> товар собран и отправлен
    # if input() == 'ls':
    #     service.satisfying_invoices()
    # # сверка через сканеры на приёме
    # if input() == 'sclad':
    #     scanner = ScannersQueue()
    #     result = scanner.process_pending_invoices(Config.RECIPIENT_WAREHOUSE)
    #     print(f"Обработано накладных: {result['total']}")
    #     print(f"Успешно принято: {result['received']}")
    #     print(f"Требуют повторной проверки: {len(result['retries'])}")
    #     print(f"Накладные с ошибками: {len(result['errors'])}")
    # # размещение товара на складе
    # if input() == 'append':
    #     services.check_delivery()
