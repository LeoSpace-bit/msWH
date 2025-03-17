#config.py
import os
import sys


class Config:
    # Warehouse Settings
    DEFAULT_STOCK_ITEM_ID = 2**31 - 1
    RECIPIENT_WAREHOUSE = 'WHAAAAAARUS060ru00000002'

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

    # Kafka
    KAFKA_BROKERS = os.getenv('KAFKA_BROKERS', 'localhost:9092').split(',')
    KAFKA_GROUP_ID = os.getenv('KAFKA_GROUP_ID', 'warehouse-group')

    # Safety
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds