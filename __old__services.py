# __old__services.py
from datetime import datetime, timedelta
import time
from threading import Thread, Lock
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from models import db, Invoice, InvoiceItem, StockItem, StorageLocation, StorageCell, LegalEntity
from config import Config

class LogisticsService:
    @staticmethod
    def send_invoice(invoice_id):
        """Отправка накладной в логистику"""
        try:
            invoice = Invoice.query.get(invoice_id)
            if invoice and invoice.status == 'created':
                invoice.status = 'shipping'
                db.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error updating invoice status: {e}")
            return False

class AllocationService:
    @staticmethod
    def check_zone_availability(zone_name, required):
        """Проверка доступности ячеек в зоне"""
        zone = StorageLocation.query.filter_by(zone=zone_name).first()
        if not zone:
            return False
        free_cells = StorageCell.query.filter_by(
            zone_id=zone.id,
            pgd_id=-1
        ).count()
        return free_cells >= required

    @staticmethod
    def allocate_items(zone_name, items):
        try:
            zone = StorageLocation.query.filter_by(zone=zone_name).first()
            if not zone:
                return False

            cells = StorageCell.query.filter_by(
                zone_id=zone.id,
                pgd_id=-1  # Свободные ячейки
            ).limit(len(items)).all()

            if len(cells) < len(items):
                return False

            for cell, item in zip(cells, items):
                stock_item = StockItem.query.get(item['stock_item_id'])
                if not stock_item:
                    raise ValueError(f"StockItem {item['stock_item_id']} not found")

                stock_item.quantity += item['quantity']
                stock_item.location_id = zone.id  # Обновляем зону
                cell.pgd_id = stock_item.id  # Теперь используем StockItem.id

            db.session.commit()
            return True

        except (SQLAlchemyError, ValueError) as e:
            db.session.rollback()
            print(f"Allocation error: {e}")
            return False

class ScannersQueue:
    _queue = []
    _running = False
    _thread = None
    _lock = Lock()

    @classmethod
    def add_to_queue(cls, data):
        with cls._lock:
            cls._queue.append(data)

    @classmethod
    def start_processing(cls, app):
        with cls._lock:
            if cls._running:
                return
            cls._running = True
            cls._thread = Thread(
                target=cls._process_loop,
                args=(app,),
                daemon=True
            )
            cls._thread.start()

    @classmethod
    def _process_loop(cls, app):
        with app.app_context():
            while cls._running:
                cls.process_queue()
                time.sleep(1)

    @classmethod
    def process_queue(cls):
        current_time = datetime.utcnow()
        processed = []
        with cls._lock:
            queue_copy = list(enumerate(cls._queue))

        for idx, item in queue_copy:
            if datetime.fromisoformat(item['unloading_time']) <= current_time:
                if cls._process_item(item):
                    processed.append(idx)

        with cls._lock:
            for idx in reversed(sorted(processed)):
                del cls._queue[idx]

    @classmethod
    def _process_item(cls, item):
        try:
            invoice = Invoice.query.get(item['invoice_id'])
            if not invoice:
                return False

            items_data = item['items']
            for inv_item in invoice.items:
                match = next(
                    (i for i in items_data
                     if i['stock_item_id'] == inv_item.stock_item_id
                     and i['quantity'] == inv_item.quantity
                     and i['batch_number'] == inv_item.batch_number),
                    None
                )
                if not match:
                    invoice.status = 'error'
                    db.session.commit()
                    return False

            success = AllocationService.allocate_items(
                zone_name='Safe',
                items=[{'stock_item_id': it.stock_item_id, 'quantity': it.quantity} for it in invoice.items]
            )

            if success:
                invoice.status = 'completed'
            else:
                invoice.status = 'error'

            db.session.commit()
            return success

        except Exception as e:
            db.session.rollback()
            print(f"Processing error: {e}")
            invoice.status = 'error'
            db.session.commit()
            return False

    @classmethod
    def stop_processing(cls):
        with cls._lock:
            if not cls._running:
                return
            cls._running = False
            thread = cls._thread
            cls._thread = None
            cls._queue.clear()
        if thread and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                print("Warning: Scanner thread did not terminate gracefully")


def create_invoice(invoice_type, shipper_id, items_data, consignee_id=None):
    try:
        # Проверка контрагентов и StockItem (как в предыдущих исправлениях)
        # ... (код проверок контрагентов и StockItem) ...

        # Создание Invoice
        invoice = Invoice(
            invoice_type=invoice_type,
            status='created',
            recipient_warehouse=Config.RECIPIENT_WAREHOUSE,
            shipper_id=shipper_id,
            consignee_id=consignee_id
        )
        db.session.add(invoice)
        db.session.flush()  # Получаем invoice.id

        # Создание InvoiceItem с корректными датами
        for item in items_data:
            # Преобразование строк в объекты date
            production_date = datetime.strptime(
                item['production_date'], '%Y-%m-%d'
            ).date()
            expiration_date = datetime.strptime(
                item['expiration_date'], '%Y-%m-%d'
            ).date()

            invoice_item = InvoiceItem(
                production_date=production_date,
                expiration_date=expiration_date,
                quantity=item['quantity'],
                batch_number=item['batch_number'],
                invoice_id=invoice.id,
                stock_item_id=item['stock_item_id']
            )
            db.session.add(invoice_item)

        db.session.commit()
        return invoice.id

    except (SQLAlchemyError, ValueError) as e:
        db.session.rollback()
        print(f"Error creating invoice: {e}")
        return None

def check_delivery():
    """Проверка готовности доставки"""
    try:
        invoices = Invoice.query.filter(
            Invoice.invoice_type == 'arrival',
            Invoice.status == 'shipping',
            Invoice.recipient_warehouse == Config.RECIPIENT_WAREHOUSE
        ).all()

        for invoice in invoices:
            items_data = [{
                'stock_item_id': item.stock_item_id,
                'quantity': item.quantity,
                'batch_number': item.batch_number,
                'pgd_id': item.stock_item.pgd_id  # Добавляем pgd_id
            } for item in invoice.items]

            ScannersQueue.add_to_queue({
                'invoice_id': invoice.id,
                'items': items_data,
                'unloading_time': (datetime.utcnow() + timedelta(seconds=15)).isoformat()
            })
        return len(invoices)
    except SQLAlchemyError as e:
        print(f"Delivery check error: {e}")
        return 0