# app.py
import logging
import threading
import time
import services
from config import Config
from sqlalchemy.exc import SQLAlchemyError
from services import LogisticsService, ScannersQueue

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger('MainApp')
    stock_monitor = None
    invoice_processor = None

    try:
        invoice_processor = services.InvoiceProcessor() #хз, работает ли
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
        warehouse_accept_invoice = services.WarehouseAcceptInvoice()

        # ... остальная инициализация
        logger.info("Warehouse service started")

        # Основной цикл
        logistics_service = LogisticsService()
        scanners_queue = ScannersQueue()
        logger.info("Services for automated invoice processing initialized.")
        logger.info("Warehouse service fully started. Starting main processing loop.")

        # --- НАЧАЛО БЛОКА АВТОМАТИЗАЦИИ ---
        # Основной цикл для автоматического продвижения накладных по статусам
        while True:
            try:
                # --- Шаг 1: Перевод ARRIVAL из CREATED в SHIPPING ---
                # Накладные типа ARRIVAL создаются в статусе CREATED сервисом WarehouseAcceptInvoice.
                # Функция satisfying_invoices переводит их в SHIPPING.
                result_satisfying = logistics_service.satisfying_invoices()
                # Логируем, только если были изменения
                updated_count_str = result_satisfying.get("message", "").split(" ")[1] if result_satisfying.get(
                    "message") else "0"
                if updated_count_str.isdigit() and int(updated_count_str) > 0:
                    logger.info(f"Auto-Step 1 (Satisfying): {result_satisfying.get('message')}")

                # --- Шаг 2: Обработка сканером (ARRIVAL из SHIPPING в RECEIVED) ---
                # Функция process_pending_invoices имитирует сканирование и переводит
                # накладные ARRIVAL со статусом SHIPPING в RECEIVED (или обрабатывает ошибки/повторы).
                result_scan = scanners_queue.process_pending_invoices(Config.RECIPIENT_WAREHOUSE)
                # Логируем, только если были обработанные, ошибки или повторы
                if result_scan and (
                        result_scan.get('received', 0) > 0 or result_scan.get('retries') or result_scan.get('errors')):
                    logger.info(
                        f"Auto-Step 2 (Scanning): Total={result_scan.get('total', 0)}, Received={result_scan.get('received', 0)}, Retries={len(result_scan.get('retries', []))}, Errors={len(result_scan.get('errors', []))}")
                    if result_scan.get('errors'):
                        logger.warning(f"Scanning errors detected: {result_scan['errors']}")
                    if result_scan.get('retries'):
                        logger.warning(f"Scanning retries needed: {result_scan['retries']}")
                elif result_scan.get('status') == 'error':
                    logger.error(f"Auto-Step 2 (Scanning): Critical error - {result_scan.get('message')}")

                # --- Шаг 3: Размещение на складе (ARRIVAL из RECEIVED в COMPLETED) ---
                # Функция check_delivery обрабатывает накладные ARRIVAL со статусом RECEIVED,
                # распределяет товары по ячейкам и переводит статус в COMPLETED.
                # ВАЖНО: check_delivery - это функция модуля services, а не метод класса.
                result_delivery = services.check_delivery()
                # Логируем, только если были обработанные накладные или произошла ошибка
                if result_delivery and result_delivery.get('processed_invoices', 0) > 0:
                    logger.info(
                        f"Auto-Step 3 (Delivery Check): Processed {result_delivery['processed_invoices']} invoices.")
                elif result_delivery and result_delivery.get('error'):
                    logger.error(f"Auto-Step 3 (Delivery Check): Failed - {result_delivery['error']}")

                # --- Обработка Отгрузок (DEPARTURE) --- # Не требует реализации
                # Накладные DEPARTURE создаются сервисом WarehouseAcceptInvoice сразу в статусе SHIPPING (если успешно).
                # -TO-DO-: Добавить логику для завершения отгрузок (перевод из SHIPPING в COMPLETED).
                #       Возможно, потребуется отдельная логика или вызов scanners_queue.process_departure(invoice_id),
                #       но для этого нужно сначала получить ID накладных DEPARTURE в статусе SHIPPING.
                # Пример:
                # session_dep = Session() # Нужна сессия БД
                # try:
                #    departure_shipping_invoices = session_dep.query(Invoice.id).filter(
                #        Invoice.invoice_type == InvoiceType.DEPARTURE,
                #        Invoice.status == InvoiceStatus.SHIPPING
                #    ).all()
                #    for inv_id_tuple in departure_shipping_invoices:
                #        inv_id = inv_id_tuple[0]
                #        logger.info(f"Attempting to complete DEPARTURE invoice {inv_id}")
                #        # scanners_queue.process_departure(inv_id) # Эта функция пока просто меняет статус на COMPLETED
                # finally:
                #    session_dep.close()


            except SQLAlchemyError as db_err:
                logger.error(f"Database error in main processing loop: {db_err}", exc_info=True)
                # Пауза перед повторной попыткой при ошибке БД
                time.sleep(15)
            except Exception as loop_error:
                logger.error(f"Error in main processing loop: {loop_error}", exc_info=True)
                # Общая пауза в случае других ошибок
                time.sleep(10)

            # Пауза между циклами автоматической обработки
            time.sleep(10)  # Например, 10 секунд

        # --- КОНЕЦ БЛОКА АВТОМАТИЗАЦИИ ---


    except KeyboardInterrupt:

        logger.info("Shutting down initiated by user (KeyboardInterrupt)...")

    except Exception as e:

        logger.critical(f"Critical error during startup or main execution: {str(e)}",
                        exc_info=True)  # Логируем критическую ошибку

    finally:

        logger.info("Stopping services...")
        # Убедимся что метод stop есть и вызываем его
        if stock_monitor:
            if hasattr(stock_monitor, 'stop_monitoring') and callable(stock_monitor.stop_monitoring):
                stock_monitor.stop_monitoring()
            elif hasattr(stock_monitor, 'stop') and callable(stock_monitor.stop):
                stock_monitor.stop()

        # Останавливаем другие сервисы, если у них есть метод stop
        if warehouse_accept_invoice and hasattr(warehouse_accept_invoice, 'stop') and callable(
                warehouse_accept_invoice.stop):
            warehouse_accept_invoice.stop()

        if registry and hasattr(registry, 'stop') and callable(
                registry.stop):  # У WarehouseRegistry нет метода stop, но можно добавить

            registry.running = False  # Пример остановки для Registry

        if warehouse_heartbeat and hasattr(warehouse_heartbeat, 'stop') and callable(warehouse_heartbeat.stop):
            warehouse_heartbeat.stop()

        if goods_handler and hasattr(goods_handler, 'stop') and callable(
                goods_handler.stop):  # У GoodsRequestHandler нет метода stop, но можно добавить

            goods_handler.running = False  # Пример

        if warehouse_state_invoice and hasattr(warehouse_state_invoice, 'stop') and callable(
                warehouse_state_invoice.stop):
            warehouse_state_invoice.stop()

        # Закрытие других ресурсов если необходимо

        logger.info("Warehouse service stopped.")

# Пример того как я выполнял ручное тестирование прохождения состояний
"""
# пример создания накладной для получение товара (for arrival)
# def create_invoice(logistic_service: LogisticsService):
#     #формируем список товаров для заказа на получение (id, количество)
#     items = [
#         (5, 50)
#     ]
#     sender = "WHAAAAAARUS060ru01100001"  # 24 символа, отправитель - просто не трогай и вставляй всегда его как заглушку
#     logistic_service.create_invoice_request(items, sender) # вызов функции обработчика (глубже опускаться не надо, достаточно вызывать её и передавать параметры)
#
# # пример создания накладной для отправки/списания товара (for departure)
# def departure_invoice(logistic_service: LogisticsService):
#     # формируем список товаров для заказа на отправку (id, количество)
#     items = [
#         (5, 10)
#     ]
#     reciver = "WHAAAAAARUS060ru01100001"  # 24 символа, получатель - просто не трогай и вставляй всегда его как заглушку
#     logistic_service.create_departure_invoice(items, Config.RECIPIENT_WAREHOUSE, reciver) # вызов функции обработчика (глубже опускаться не надо, достаточно вызывать её и передавать параметры)



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