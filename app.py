# app.py
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
    items = [
        (5, 50)
    ]
    sender = "WHAAAAAARUS060ru01100001"  # 24 символа
    logistic_service.create_invoice_request(items, sender)


def departure_invoice(logistic_service: LogisticsService):
    items = [
        (5, 10)
    ]
    reciver = "WHAAAAAARUS060ru01100001"  # 24 символа
    logistic_service.create_departure_invoice(items, Config.RECIPIENT_WAREHOUSE, reciver)


if __name__ == '__main__':
    create_app()
    service = LogisticsService()

    if input() == 'yes':
        departure_invoice(service)
        exit(201)

    # запрашиваем товар через накладную
    if input() == 'si':
        create_invoice(service)
    # выполняем функцию LS --> товар собран и отправлен
    if input() == 'ls':
        service.satisfying_invoices()
    # сверка через сканеры на приёме
    if input() == 'sclad':
        scanner = ScannersQueue()
        result = scanner.process_pending_invoices(Config.RECIPIENT_WAREHOUSE)
        print(f"Обработано накладных: {result['total']}")
        print(f"Успешно принято: {result['received']}")
        print(f"Требуют повторной проверки: {len(result['retries'])}")
        print(f"Накладные с ошибками: {len(result['errors'])}")
    # размещение товара на складе
    if input() == 'append':
        services.check_delivery()
