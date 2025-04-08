#services.py
import time
from datetime import datetime, timedelta, timezone
import random

import logger
from kafka.errors import NoBrokersAvailable
from sqlalchemy.exc import SQLAlchemyError
from kafka import KafkaProducer, KafkaConsumer
import json
import threading
import logging

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
                # Количество ЗАНЯТЫХ ячеек (исключая пустые)
                used_cells = session.query(StockAllocation).filter(
                    StockAllocation.storage_location_id == zone.id,
                    StockAllocation.stock_item_id != Config.DEFAULT_STOCK_ITEM_ID
                ).count()

                available = zone.capacity - used_cells
                if available >= total_quantity:
                    suitable_zones.append(zone)

            if not suitable_zones:
                raise ValueError(
                    f"Недостаточно свободных ячеек. Требуется: {total_quantity}, "
                    f"доступно в зонах: {[z.sector_name for z in zones]}"
                )
        finally:
            session.close()

    def create_invoice_request(self, items: list[tuple[int, int]], sender: str)  -> Invoice:
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
            return new_invoice  # Явно возвращаем объект

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

    def create_departure_invoice(self, items: list[tuple[int, int]],
                                 sender_warehouse: str,
                                 receiver_warehouse: str) -> Invoice:
        """
        Создание накладной на отгрузку товаров
        """
        # 1. Валидация складов
        if len(sender_warehouse) != 24 or len(receiver_warehouse) != 24:
            raise ValueError("Названия складов должны быть 24 символа")

        if sender_warehouse == receiver_warehouse:
            raise ValueError("Склады отправителя и получателя не могут совпадать")

        session = self.Session()
        try:
            # 2. Проверка наличия товаров
            status = InvoiceStatus.CREATED
            for pgd_id, qty in items:
                stock_item = session.query(StockItem).filter_by(pgd_id=pgd_id).first()
                if not stock_item or stock_item.quantity < qty:
                    status = InvoiceStatus.REJECTED
                    break

            # Создаем накладную
            new_invoice = Invoice(
                invoice_type=InvoiceType.DEPARTURE,
                status=status,
                created_at=datetime.utcnow(),
                sender_warehouse=sender_warehouse,
                receiver_warehouse=receiver_warehouse
            )
            session.add(new_invoice)
            session.flush()

            if status == InvoiceStatus.REJECTED:
                session.commit()
                return new_invoice

            # 3. Создание элементов накладной
            invoice_items = []
            for pgd_id, qty in items:
                invoice_items.append(InvoiceItem(
                    invoice_id=new_invoice.id,
                    pgd_id=pgd_id,
                    quantity=qty,
                    batch_number=self.generate_batch_number(),
                    production_date=datetime.utcnow() - timedelta(days=1),
                    expiration_date=datetime.utcnow() + timedelta(days=365)
                ))

            session.add_all(invoice_items)
            session.flush()

            # 4. Освобождение ячеек
            for pgd_id, qty in items:
                # Находим первые N ячеек с товаром
                cells = session.query(StockAllocation).filter(
                    StockAllocation.stock_item_id == pgd_id
                ).limit(qty).all()

                # Помечаем ячейки как свободные
                for cell in cells:
                    cell.stock_item_id = Config.DEFAULT_STOCK_ITEM_ID

                # Обновляем StockItem
                stock_item = session.query(StockItem).filter_by(pgd_id=pgd_id).first()
                stock_item.quantity -= qty

            # 5. Финализация статуса
            new_invoice.status = InvoiceStatus.SHIPPING
            session.commit()
            return new_invoice

        except Exception as e:
            session.rollback()
            new_invoice.status = InvoiceStatus.ERROR
            session.commit()
            raise e
        finally:
            session.close()

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

    def process_departure(self, invoice_id: int):
        """
        Обработка отгрузки товаров (для использования в других процессах)
        """
        session = self.Session()
        try:
            invoice = session.query(Invoice).get(invoice_id)
            if not invoice or invoice.status != InvoiceStatus.SHIPPING:
                return

            # Дополнительные проверки и логика доставки
            # ...

            invoice.status = InvoiceStatus.COMPLETED
            session.commit()

        except Exception as e:
            session.rollback()
            invoice.status = InvoiceStatus.ERROR
            session.commit()
            raise e
        finally:
            session.close()

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

class StockMonitor:
    def __init__(self):
        self.engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
        self.Session = sessionmaker(bind=self.engine)
        self.logger = logging.getLogger('StockMonitor')
        self.logger.setLevel(logging.INFO)

        try:
            self.producer = KafkaProducer(
                bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS.split(','),
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=5,
                acks='all'
            )
            self.logger.info("Kafka producer initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Kafka producer: {str(e)}")
            raise

        self.running = True

    def start_monitoring(self):
        def monitor_loop():
            self.logger.info("Starting stock monitoring service")
            while self.running:
                session = None
                try:
                    session = self.Session()
                    # Получаем актуальные данные из БД
                    try:
                        stock_items = session.query(StockItem).all()  # Получаем все товары
                        stock_data = {
                            Config.RECIPIENT_WAREHOUSE: [
                                {
                                    "pgd_id": str(item.pgd_id),  # Преобразование в строку
                                    "quantity": item.quantity,
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                                for item in stock_items
                                if item.quantity > 0  # Фильтрация нулевых остатков
                            ]
                        }
                        self.producer.send(Config.KAFKA_STOCK_TOPIC, stock_data)
                    except Exception as e:
                        self.logger.error(f"Stock monitoring error: {str(e)}")
                    finally:
                        session.close()
                        time.sleep(30)

                    # Отправляем сообщение
                    future = self.producer.send(
                        Config.KAFKA_STOCK_TOPIC,
                        value=stock_data
                    )
                    # Ожидаем подтверждения
                    future.get(timeout=10)
                    self.logger.info(f"Successfully sent stock update for warehouse {Config.RECIPIENT_WAREHOUSE}")

                except NoBrokersAvailable as e:
                    self.logger.error(f"Kafka brokers not available: {str(e)}")
                except Exception as e:
                    self.logger.error(f"Monitoring error: {str(e)}", exc_info=True)
                finally:
                    if session:
                        session.close()
                    threading.Event().wait(30)  # Интервал между проверками

        threading.Thread(target=monitor_loop, name="StockMonitor", daemon=True).start()

    def stop_monitoring(self):
        self.running = False
        self.producer.close(timeout=5)
        self.logger.info("Stock monitoring service stopped")

class InvoiceProcessor:
    def __init__(self):
        self.consumer = KafkaConsumer(
            Config.KAFKA_INVOICE_TOPIC,
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        self.service = LogisticsService()

    def start_processing(self):
        for message in self.consumer:
            try:
                data = message.value
                if data['type'] == 'arrival':
                    self.process_arrival(data)
                elif data['type'] == 'departure':
                    self.process_departure(data)
            except Exception as e:
                self.log_error(e)

    def process_arrival(self, data):
        items = [(item['pgd_id'], item['quantity']) for item in data['items']]
        # Сохраняем созданную накладную в переменную
        invoice = self.service.create_invoice_request(
            items=items,
            sender=data['warehouse']
        )
        self._send_update(invoice, 'arrival')  # Передаем объект invoice

    def process_departure(self, data):
        items = [(item['pgd_id'], item['quantity']) for item in data['items']]
        # Сохраняем созданную накладную в переменную
        invoice = self.service.create_departure_invoice(
            items=items,
            sender_warehouse=data['warehouse'],
            receiver_warehouse="WHAAAAAARUS060ru00000002"
        )
        self._send_update(invoice, 'departure')  # Передаем объект invoice

    def _send_update(self, invoice, invoice_type):
        self.producer.send('invoice_updates', {
            'id': invoice.id,
            'type': invoice_type,
            'status': invoice.status.value,
            'sender': invoice.sender_warehouse,
            'receiver': invoice.receiver_warehouse,
            'items': [{
                'id': item.pgd_id,
                'quantity': item.quantity
            } for item in invoice.items],
            'timestamp': invoice.created_at.isoformat()
        })

    def log_error(self, error):
        logger.error(f"Invoice processing error: {str(error)}")

# services.py (WH)
class WarehouseRegistry:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        self.wh_data = Config.FAKE_WAREHOUSES
        self.running = True
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.heartbeat_thread.start()

    def heartbeat(self):
        """Регулярная отправка данных каждые 30 секунд"""
        while self.running:
            self.publish_warehouse_info()
            time.sleep(30)

    def publish_warehouse_info(self):
        for wh_id, meta in self.wh_data.items():
            data = {
                'wh_id': wh_id,
                'status': 'active',
                'metadata': meta,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            # Явная сериализация в JSON
            self.producer.send(Config.KAFKA_WH_REGISTRY_TOPIC, value=data)
            print(f"Отправлены данные склада: {wh_id}")  # Логирование #self.producer.flush()

def check_delivery():
    """Обработка полученных поставок и распределение товаров по ячейкам"""
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Находим подходящие накладные
        invoices = session.query(Invoice).filter(
            Invoice.invoice_type == InvoiceType.ARRIVAL,
            Invoice.status == InvoiceStatus.RECEIVED,
            Invoice.receiver_warehouse == Config.RECIPIENT_WAREHOUSE
        ).all()

        for invoice in invoices:
            success = True
            items_to_update = {}

            try:
                # Обрабатываем каждый товар в накладной
                for item in invoice.items:
                    pgd_id = item.pgd_id
                    quantity = item.quantity

                    # Находим подходящую зону для товара
                    zone = _find_suitable_zone(session, pgd_id, quantity)
                    if not zone:
                        success = False
                        break

                    # Находим свободные ячейки в зоне
                    free_cells = session.query(StockAllocation).filter(
                        StockAllocation.storage_location_id == zone.id,
                        StockAllocation.stock_item_id == Config.DEFAULT_STOCK_ITEM_ID
                    ).limit(quantity).all()

                    if len(free_cells) < quantity:
                        success = False
                        break

                    # Занимаем ячейки
                    for cell in free_cells[:quantity]:
                        cell.stock_item_id = pgd_id

                    # Сохраняем количество для обновления StockItem
                    items_to_update[pgd_id] = items_to_update.get(pgd_id, 0) + quantity

                if success:
                    # Обновляем StockItems и статус накладной
                    _update_stock_items(session, items_to_update)
                    invoice.status = InvoiceStatus.COMPLETED
                else:
                    invoice.status = InvoiceStatus.ERROR

                session.commit()
                print(f"Накладная {invoice.id} обработана: {invoice.status}")

            except Exception as e:
                session.rollback()
                invoice.status = InvoiceStatus.ERROR
                session.commit()
                print(f"Ошибка обработки накладной {invoice.id}: {str(e)}")

        return {"processed_invoices": len(invoices)}

    except SQLAlchemyError as e:
        session.rollback()
        print(f"Ошибка базы данных: {str(e)}")
        return {"error": str(e)}
    finally:
        session.close()

def _find_suitable_zone(session, pgd_id: int, required_cells: int) -> StorageLocation:
    """Находит зону с достаточным количеством свободных ячеек для товара"""
    # Проверяем существующие зоны с товаром
    existing_zone = session.query(StockAllocation.storage_location_id).filter(
        StockAllocation.stock_item_id == pgd_id
    ).first()

    if existing_zone:
        # Проверяем доступность места в текущей зоне
        free_in_zone = session.query(StockAllocation).filter(
            StockAllocation.storage_location_id == existing_zone.storage_location_id,
            StockAllocation.stock_item_id == Config.DEFAULT_STOCK_ITEM_ID
        ).count()

        if free_in_zone >= required_cells:
            return session.get(StorageLocation, existing_zone.storage_location_id)

    # Ищем новую подходящую зону
    zones = session.query(StorageLocation).all()
    for zone in zones:
        free_cells = session.query(StockAllocation).filter(
            StockAllocation.storage_location_id == zone.id,
            StockAllocation.stock_item_id == Config.DEFAULT_STOCK_ITEM_ID
        ).count()

        if free_cells >= required_cells:
            return zone

    return None

def _update_stock_items(session, items_to_update: dict):
    """Обновляет количество товаров в StockItem"""
    for pgd_id, quantity in items_to_update.items():
        stock_item = session.query(StockItem).filter_by(pgd_id=pgd_id).first()
        if stock_item:
            stock_item.quantity += quantity
        else:
            session.add(StockItem(pgd_id=pgd_id, quantity=quantity))


class WarehouseOnlineHeartbeat:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        self.wh_id = Config.RECIPIENT_WAREHOUSE
        self.running = True
        self.heartbeat_thread = threading.Thread(
            target=self.heartbeat_loop,
            daemon=True
        )
        self.heartbeat_thread.start()

    def heartbeat_loop(self):
        while self.running:
            try:
                # Добавляем корректный timestamp
                message = {
                    'wh_id': self.wh_id,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'  # ISO 8601 с часовым поясом
                }
                self.producer.send(
                    Config.KAFKA_WAREHOUSES_ONLINE_TOPIC,
                    value=message
                )
                self.producer.flush()
                time.sleep(5)
            except Exception as e:
                logging.error(f"Heartbeat error: {str(e)}")
                time.sleep(1)

    def stop(self):
        self.running = False
        self.producer.close()


class GoodsRequestHandler:
    """Обработчик запросов товаров со склада"""

    def __init__(self):
        self.engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
        self.Session = sessionmaker(bind=self.engine)
        self.wh_id = Config.RECIPIENT_WAREHOUSE

        self.consumer = KafkaConsumer(
            Config.KAFKA_GOODS_REQUEST_TOPIC,
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            group_id='wh-goods-request-handler'
        )

        self.producer = KafkaProducer(
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )

        self.handler_thread = threading.Thread(
            target=self.process_requests,
            daemon=True
        )
        self.handler_thread.start()

    def process_requests(self):
        for message in self.consumer:
            try:
                data = message.value
                if data.get('wh_id') != self.wh_id:
                    continue

                if data.get('command') == 'get_all_goods':
                    goods = self.get_available_goods()
                    self.producer.send(
                        Config.KAFKA_GOODS_RESPONSE_TOPIC,
                        {
                            'wh_id': self.wh_id,
                            'goods': goods
                        }
                    )
            except Exception as e:
                logging.error(f"Goods request error: {str(e)}")

    def get_available_goods(self):
        """Получает список доступных товаров из БД"""
        session = self.Session()
        try:
            items = session.query(StockItem.pgd_id).filter(
                StockItem.pgd_id != Config.EMPTY_STOCK_ITEM_ID,
                StockItem.quantity > 0
            ).all()
            return [item.pgd_id for item in items]
        finally:
            session.close()