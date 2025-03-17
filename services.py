#services.py
from datetime import datetime, timedelta
import random
from sqlalchemy.exc import SQLAlchemyError

from models import Invoice, InvoiceItem, StorageLocation, StockItem, StockAllocation
from config import Config
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
import uuid
from models import InvoiceType, InvoiceStatus
from collections import defaultdict


class LogisticsService:
    def __init__(self):
        self.engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
        self.Session = sessionmaker(bind=self.engine)

    def generate_batch_number(self):
        """Генерирует уникальный номер партии"""
        return f"BATCH-{uuid.uuid4().hex[:8].upper()}"  # Пример: BATCH-A1B2C3D4

    def check_storage_capacity(self, items: list[tuple[int, int]]):
        """Проверяет наличие свободных ячеек в зонах хранения"""
        session = self.Session()
        total_quantity = sum(qty for _, qty in items)

        try:
            # Получаем все зоны хранения
            zones = session.query(StorageLocation).all()

            # Проверяем каждую зону на наличие достаточного места
            suitable_zones = []
            for zone in zones:
                # Количество занятых ячеек в зоне
                used_cells = session.query(StockAllocation).filter_by(
                    storage_location_id=zone.id
                ).count()

                available = zone.capacity - used_cells
                if available >= total_quantity:
                    suitable_zones.append(zone)

            if not suitable_zones:
                raise ValueError(
                    f"Недостаточно свободных ячеек. "
                    f"Требуется: {total_quantity}, "
                    f"доступно в зонах: {[z.sector_name for z in zones]}"
                )
        finally:
            session.close()

    def create_invoice_request(self, items: list[tuple[int, int]], sender: str):
        """Создает новый инвойс с проверками"""
        if len(sender) != 24:
            raise ValueError("Sender warehouse должен быть 24 символа")

        if sender == Config.RECIPIENT_WAREHOUSE:
            raise ValueError("Sender и Receiver не могут совпадать")

        # Проверка вместимости
        self.check_storage_capacity(items)

        session = self.Session()
        try:
            # Создаем инвойс
            new_invoice = Invoice(
                invoice_type=InvoiceType.ARRIVAL,
                status=InvoiceStatus.CREATED,
                created_at=datetime.utcnow(),
                sender_warehouse=sender,
                receiver_warehouse=Config.RECIPIENT_WAREHOUSE
            )
            session.add(new_invoice)
            session.flush()

            # Создаем элементы инвойса
            yesterday = datetime.utcnow() - timedelta(days=1)
            next_year = datetime.utcnow() + timedelta(days=365)

            invoice_items = []
            for pgd_id, qty in items:
                invoice_items.append(InvoiceItem(
                    invoice_id=new_invoice.id,
                    pgd_id=pgd_id,
                    quantity=qty,
                    batch_number=self.generate_batch_number(),
                    production_date=yesterday,
                    expiration_date=next_year
                ))

            session.add_all(invoice_items)
            session.commit()
            print(f"Накладная [ поставка ] {new_invoice.id} создан с {len(items)} позициями")

        except Exception as e:
            session.rollback()
            print(f"Ошибка: {str(e)}")
            raise
        finally:
            session.close()

    def satisfying_invoices(self):
        """
        Обновляет статус счетов с типом ARRIVAL и статусом CREATED на SHIPPING.

        Args:
            session (Session): Сессия SQLAlchemy для работы с базой данных.

        Returns:
            dict: Словарь с сообщением о количестве обновленных счетов.

        Raises:
            SQLAlchemyError: В случае ошибки при работе с базой данных.
        """
        session = self.Session()

        try:
            # Выполняем массовое обновление статуса счетов
            updated_count = session.query(Invoice).filter(
                Invoice.invoice_type == InvoiceType.ARRIVAL,
                Invoice.status == InvoiceStatus.CREATED
            ).update(
                {Invoice.status: InvoiceStatus.SHIPPING},
                synchronize_session='evaluate'
            )
            session.commit()  # Фиксируем изменения
            return {"message": f"Updated {updated_count} invoices to SHIPPING status."}
        except SQLAlchemyError as e:
            session.rollback()  # Откатываем изменения при ошибке
            raise e
        except Exception as e:
            session.rollback()
            raise e


class BatchScanner:
    """Симулятор сканера штрих-кодов"""

    def simulate_scan(self, expected_batch: str) -> str:
        """Имитирует процесс сканирования с 15% вероятностью ошибки"""
        if random.random() < 0.1:
            return self._generate_incorrect_batch(expected_batch)
        return expected_batch

    def _generate_incorrect_batch(self, base: str) -> str:
        """Генерирует некорректный batch number"""
        variants = [
            base[:-1] + 'X',  # Замена последнего символа
            base.upper() if base.islower() else base.lower(),  # Смена регистра
            f"ERR-{base[:4]}",  # Добавление префикса
            base.replace('B', '8')  # Замена похожих символов
        ]
        return random.choice(variants)


class ScannersQueue:
    """Обработчик очереди сканирования для склада"""

    def __init__(self):
        self.engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
        self.Session = sessionmaker(bind=self.engine)
        self.retry_registry = defaultdict(int)
        self.scanner = BatchScanner()

    def process_pending_invoices(self, warehouse_id: str) -> dict:
        """
        Основной метод обработки накладных для конкретного склада
        :param warehouse_id: Идентификатор склада-получателя
        :return: Статистика обработки
        """
        session = self.Session()
        try:
            invoices = self._get_invoices(session, warehouse_id)
            result = self._process_invoices(session, invoices)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            session.close()

    def _get_invoices(self, session: Session, warehouse_id: str) -> list[Invoice]:
        """Получает накладные для обработки"""
        return session.query(Invoice).filter(
            Invoice.invoice_type == InvoiceType.ARRIVAL,
            Invoice.receiver_warehouse == warehouse_id,
            Invoice.status == InvoiceStatus.SHIPPING
        ).all()

    def _process_invoices(self, session: Session, invoices: list[Invoice]) -> dict:
        """Обрабатывает список накладных"""
        result = {
            "total": len(invoices),
            "received": 0,
            "errors": [],
            "retries": []
        }

        for invoice in invoices:
            process_result = self._process_single_invoice(session, invoice)

            if process_result["status"] == "received":
                result["received"] += 1
            elif process_result["status"] == "error":
                result["errors"].append(process_result)
            else:
                result["retries"].append(process_result)

        return result

    def _process_single_invoice(self, session: Session, invoice: Invoice) -> dict:
        """Обрабатывает одну накладную"""
        try:
            errors = []

            for item in invoice.items:
                scanned = self.scanner.simulate_scan(item.batch_number)
                if scanned != item.batch_number:
                    errors.append({
                        "item_id": item.pgd_id,
                        "expected": item.batch_number,
                        "scanned": scanned
                    })

            if errors:
                return self._handle_scan_errors(invoice, errors)

            return self._handle_success(session, invoice)

        except Exception as e:
            return self._handle_critical_error(invoice, e)

    def _handle_scan_errors(self, invoice: Invoice, errors: list) -> dict:
        """Обрабатывает ошибки сканирования"""
        self.retry_registry[invoice.id] += 1

        if self.retry_registry[invoice.id] >= 2:
            del self.retry_registry[invoice.id]
            return {
                "invoice_id": invoice.id,
                "status": "error",
                "errors": errors,
                "message": "Достигнут лимит попыток сканирования"
            }

        return {
            "invoice_id": invoice.id,
            "status": "retry",
            "errors": errors,
            "retry_count": self.retry_registry[invoice.id]
        }

    def _handle_success(self, session: Session, invoice: Invoice) -> dict:
        """Обрабатывает успешное сканирование"""
        invoice.status = InvoiceStatus.RECEIVED
        session.add(invoice)

        if invoice.id in self.retry_registry:
            del self.retry_registry[invoice.id]

        return {
            "invoice_id": invoice.id,
            "status": "received"
        }

    def _handle_critical_error(self, invoice: Invoice, error: Exception) -> dict:
        """Обрабатывает критические ошибки"""
        if invoice.id in self.retry_registry:
            del self.retry_registry[invoice.id]

        return {
            "invoice_id": invoice.id,
            "status": "error",
            "message": f"Системная ошибка: {str(error)}"
        }


