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

# пример создания накладной для получение товара (for arrival)
def create_invoice(logistic_service: LogisticsService):
    #формируем список товаров для заказа на получение (id, количество)
    items = [
        (5, 50)
    ]
    sender = "WHAAAAAARUS060ru01100001"  # 24 символа, отправитель - просто не трогай и вставляй всегда его как заглушку
    logistic_service.create_invoice_request(items, sender) # вызов функции обработчика (глубже опускаться не надо, достаточно вызывать её и передавать параметры)

# пример создания накладной для отправки/списания товара (for departure)
def departure_invoice(logistic_service: LogisticsService):
    # формируем список товаров для заказа на отправку (id, количество)
    items = [
        (5, 10)
    ]
    reciver = "WHAAAAAARUS060ru01100001"  # 24 символа, получатель - просто не трогай и вставляй всегда его как заглушку
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
        #threading.Thread(target=kafka_consumer, daemon=True).start()

        # Инициализация монитора
        stock_monitor = services.StockMonitor()
        stock_monitor.start_monitoring()
        logger.info("Warehouse service started")

        registry = services.WarehouseRegistry()
        # logger.info("Warehouse registry started")
        # Убрать вызов publish_warehouse_info(), так как heartbeat работает автоматически

        warehouse_heartbeat = services.WarehouseOnlineHeartbeat()
        goods_handler = services.GoodsRequestHandler()

        warehouse_state_invoice = services.WarehouseStateInvoice()
        warehouse_logistics_invoice = services.WarehouseAcceptInvoice()

        # ... остальная инициализация
        logger.info("Warehouse service started")

        # Основной цикл
        # TODO Может тут сделать постоянную проверку очереди для warehouse_logistics_invoice?
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

# Пример того как я выполнял ручное тестирование прохождения состояний, требуется автоматизировать
"""
    create_app()
    service = LogisticsService()

    # # ручные тестовые вызовы
    (for departure):
    # # вызов функции на отправку товара от нас 
    # if input() == 'di':
        departure_invoice(service)
        exit(201)

    (for arrival):
    # вызов функция на получения товара от кого то в этот склад 
    # 1 шаг. запрашиваем товар через накладную (создаём накладную через create_invoice)
    if input() == 'si':
        create_invoice(service)
    # 2 шаг. выполняем функцию satisfying_invoices --> товар собран и отправлен
    if input() == 'ls':
        service.satisfying_invoices()
    # 3 шаг. сверка через сканеры на приёме
    if input() == 'sclad':
        scanner = ScannersQueue()
        result = scanner.process_pending_invoices(Config.RECIPIENT_WAREHOUSE)
        print(f"Обработано накладных: {result['total']}")
        print(f"Успешно принято: {result['received']}")
        print(f"Требуют повторной проверки: {len(result['retries'])}")
        print(f"Накладные с ошибками: {len(result['errors'])}")
    # 4 шаг. размещение товара на складе
    if input() == 'append':
        services.check_delivery()
"""