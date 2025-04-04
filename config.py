#config.py
import os

class Config:
    # Warehouse Settings
    DEFAULT_STOCK_ITEM_ID = 0
    RECIPIENT_WAREHOUSE = 'WHAAAAAARUS060ru00000002' # личный уникальный номер

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

    FAKE_WAREHOUSES = {
        'WHAAAAAARUS060ru00000001': {
            'name': 'Основной склад',
            'location': 'Москва'
        },
        'WHBBBBBBRUS060ru00000002': {
            'name': 'Резервный склад',
            'location': 'Санкт-Петербург'
        }
    }

    # В config.py WH добавить:
    KAFKA_BOOTSTRAP_SERVERS = 'localhost:29092'
    KAFKA_STOCK_TOPIC = 'warehouse_stock_updates'
    KAFKA_INVOICE_TOPIC = 'invoice_requests'
    KAFKA_WH_REGISTRY_TOPIC = 'warehouse_registry'