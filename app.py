# app.py
import json
import logging
import threading
import time
from datetime import datetime

from kafka import KafkaConsumer, KafkaProducer

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


def kafka_consumer():
    service = LogisticsService()
    consumer = KafkaConsumer(
        'invoice_requests',
        bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )

    producer = KafkaProducer(
        bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

    for message in consumer:
        data = message.value
        try:
            invoice = None  # Объявляем переменную заранее

            if data['type'] == 'arrival':
                # Получаем созданную накладную из метода
                invoice = service.create_invoice_request(
                    items=[(item['id'], item['quantity']) for item in data['items']],
                    sender=data['sender']
                )
            elif data['type'] == 'departure':
                # Получаем созданную накладную из метода
                invoice = service.create_departure_invoice(
                    items=[(item['id'], item['quantity']) for item in data['items']],
                    sender_warehouse=data['sender'],
                    receiver_warehouse=data['receiver']
                )

            # Проверяем успешное создание накладной
            if invoice:
                producer.send('invoice_updates', {
                    'id': invoice.id,
                    'type': data['type'],
                    'status': invoice.status.value,  # Используем реальный статус
                    'sender': data['sender'],
                    'receiver': data['receiver'],
                    'items': data['items'],
                    'timestamp': datetime.utcnow().isoformat()
                })

        except Exception as e:
            print(f"Error processing invoice: {str(e)}")
            producer.send('invoice_errors', {
                'error': str(e),
                'data': data,
                'timestamp': datetime.utcnow().isoformat()
            })



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
        threading.Thread(target=kafka_consumer, daemon=True).start()

        # Инициализация монитора
        stock_monitor = services.StockMonitor()
        stock_monitor.start_monitoring()
        logger.info("Warehouse service started")

        registry = services.WarehouseRegistry()
        # Убрать вызов publish_warehouse_info(), так как heartbeat работает автоматически
        logger.info("Warehouse registry started")

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
