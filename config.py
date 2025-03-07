import os

class Config:
    # Database
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///local_wh.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Inventory Settings
    RECIPIENT_WAREHOUSE = 'WHAAAAAARUS060ru00000002'
    REPLENISH_THRESHOLD = 0.1  # нормализованные 0..1
    BLOCK_THRESHOLD = 0.95     # нормализованные 0..1
    UNBLOCK_THRESHOLD = 0.75   # нормализованные 0..1

    # Kafka
    KAFKA_BROKERS = os.getenv('KAFKA_BROKERS', 'localhost:9092').split(',')
    KAFKA_GROUP_ID = os.getenv('KAFKA_GROUP_ID', 'warehouse-group')



    # Safety
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds