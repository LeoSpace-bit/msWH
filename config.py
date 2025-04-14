#config.py
import os

class Config:
    # Warehouse Settings
    RECIPIENT_WAREHOUSE = 'WHAAAAAARUS060ru00000002' # личный уникальный номер
    EMPTY_STOCK_ITEM_ID = 1  # ID пустого товара
    DEFAULT_STOCK_ITEM_ID = EMPTY_STOCK_ITEM_ID

    # В config.py WH добавить:
    KAFKA_BOOTSTRAP_SERVERS = 'localhost:29092'
    KAFKA_STOCK_TOPIC = 'warehouse_stock_updates'
    KAFKA_INVOICE_TOPIC = 'invoice_requests'
    KAFKA_WH_REGISTRY_TOPIC = 'warehouse_registry'
    KAFKA_WAREHOUSES_ONLINE_TOPIC = 'warehouses_online'
    KAFKA_GOODS_REQUEST_TOPIC = 'warehouse_goods_request'
    KAFKA_GOODS_RESPONSE_TOPIC = 'warehouse_goods_response'

    KAFKA_STATE_INVOICE_TOPIC = 'warehouse_state_invoice'

    FAKE_WAREHOUSES = {
        RECIPIENT_WAREHOUSE: {
            'name': 'Основной склад',
            'location': 'Москва'
        },
        'WHBBBBBBRUS060ru00000002': {
            'name': 'Резервный склад',
            'location': 'Санкт-Петербург'
        }
    }


    # Database
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key'
    SQLALCHEMY_DATABASE_URI = "sqlite:///storage_wh.db"

    # Zone Settings
    ZONE_SETTINGS = {
        'Safe': {
            'capacity': 10000,  # Максимальное количество ячеек
            'rules': {
                'replenish_threshold': 0.1,
                'block_threshold': 0.95,
                'unblock_threshold': 0.75
            }
        },
        'Flammable': {
            'capacity': 500,
            'rules': {
                'replenish_threshold': 0.2,
                'block_threshold': 0.90,
                'unblock_threshold': 0.70
            }
        }
    }

