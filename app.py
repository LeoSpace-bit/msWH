# app.py
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
        (1, 10),
        (3, 20)
    ]
    sender = "WHAAAAAARUS060ru01100008"  # 24 символа
    logistic_service.create_invoice_request(items, sender)

if __name__ == '__main__':
    create_app()
    service = LogisticsService()

    #запрашиваем товар через накладную
    #create_invoice(service)

    #выполняем функцию LS --> товар собран и отправлен
    if input() == 'si':
        service.satisfying_invoices()
    elif input() == 'sclad':
        scanner = ScannersQueue()
        result = scanner.process_pending_invoices(Config.RECIPIENT_WAREHOUSE)
        print(f"Обработано накладных: {result['total']}")
        print(f"Успешно принято: {result['received']}")
        print(f"Требуют повторной проверки: {len(result['retries'])}")
        print(f"Накладные с ошибками: {len(result['errors'])}")
