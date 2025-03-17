# commands.py
import argparse
from alembic import command
from models import Base, StorageLocation, StockItem, StockAllocation
from config import Config as AppConfig, Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def init_db():
    engine = create_engine(AppConfig.SQLALCHEMY_DATABASE_URI)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Только инициализация зон и товаров
        for zone, settings in AppConfig.ZONE_SETTINGS.items():
            if not session.query(StorageLocation).filter_by(sector_name=zone).first():
                session.add(StorageLocation(sector_name=zone, capacity=settings['capacity']))

        if session.query(StockItem).count() == 0:
            for pgd_id in range(1, 31):
                session.add(StockItem(pgd_id=pgd_id, quantity=0))

        session.commit()
        print("База инициализирована без размещения товаров по зонам")
    finally:
        session.close()


def expand_cells():
    """Создание недостающих ячеек хранения согласно конфигурации"""
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        stock_item_255 = session.query(StockItem).filter_by(pgd_id=Config.DEFAULT_STOCK_ITEM_ID).first()
        if stock_item_255 is None:
            # Если нет, добавляем StockItem с pgd_id=255 и quantity=0
            session.add(StockItem(pgd_id=Config.DEFAULT_STOCK_ITEM_ID, quantity=0))
            session.commit()  # Фиксируем изменения
            print("Создан StockItem с pgd_id: Config.DEFAULT_STOCK_ITEM_ID")
        else:
            print("StockItem с pgd_id [ Config.DEFAULT_STOCK_ITEM_ID ] уже существует.")

    finally:
        session.close()

    try:
        # Проверка и создание дефолтного StockItem
        default_item_id = Config.DEFAULT_STOCK_ITEM_ID
        stock_item = session.query(StockItem).filter_by(pgd_id=default_item_id).first()

        if not stock_item:
            session.add(StockItem(pgd_id=default_item_id, quantity=0))
            session.commit()
            print(f"Создан StockItem с pgd_id: {default_item_id}")
        else:
            print(f"StockItem с pgd_id [{default_item_id}] уже существует")

        # Получаем текущие зоны хранения
        zones = session.query(StorageLocation).all()

        for zone in zones:
            zone_name = zone.sector_name
            if zone_name not in Config.ZONE_SETTINGS:
                continue

            zone_cfg = Config.ZONE_SETTINGS[zone_name]
            expected_cells = set(range(1, zone_cfg['capacity'] + 1))

            # Получаем существующие ячейки (исправленная версия)
            existing_cells = {
                cell[0] for cell in
                session.query(StockAllocation.cell_id)
                .filter(StockAllocation.storage_location_id == zone.id)
                .all()
            }

            missing_cells = expected_cells - existing_cells

            if not missing_cells:
                print(f"Зона {zone_name} (id={zone.id}) содержит все {zone_cfg['capacity']} ячеек")
                continue

            # Пакетная вставка
            batch = [
                StockAllocation(
                    storage_location_id=zone.id,
                    cell_id=cell_id,
                    stock_item_id=default_item_id
                )
                for cell_id in sorted(missing_cells)
            ]

            session.bulk_save_objects(batch)
            session.commit()
            print(f"Добавлено {len(missing_cells)} ячеек в зону {zone_name}")

    except Exception as e:
        session.rollback()
        print(f"Ошибка: {str(e)}")
        raise
    finally:
        session.close()



def seed_stock_items():
    """Заполнение StockItem товарами (если таблица пуста)"""
    engine = create_engine(AppConfig.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        if session.query(StockItem).count() == 0:
            for pgd_id in range(1, 31):
                session.add(StockItem(pgd_id=pgd_id, quantity=0))
            session.commit()
            print("Добавлены 30 товарных позиций")
        else:
            print("Таблица StockItem уже содержит данные")
    finally:
        session.close()


def run_migrations():
    """Применение миграций Alembic"""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("Миграции успешно применены")


def create_migration(message):
    """Создание новой миграции"""
    alembic_cfg = Config("alembic.ini")
    command.revision(alembic_cfg, autogenerate=True, message=message)
    print(f"Миграция создана: {message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Управление БД и миграциями")
    subparsers = parser.add_subparsers(dest="command")

    # Регистрация команд
    subparsers.add_parser("init", help="Полная инициализация БД")
    subparsers.add_parser("seed", help="Заполнение StockItem товарами")
    subparsers.add_parser("migrate", help="Применить миграции")

    # Команда создания миграции с обязательным сообщением
    revision_parser = subparsers.add_parser("revision", help="Создать новую миграцию")
    revision_parser.add_argument("-m", "--message", required=True, help="Описание изменений")


    subparsers.add_parser("cell", help="Добавление ячеек")


    args = parser.parse_args()

    if args.command == "init":
        init_db()
    elif args.command == "seed":
        seed_stock_items()
    elif args.command == "migrate":
        run_migrations()
    elif args.command == "revision":
        create_migration(args.message)
    elif args.command == "cell":
        expand_cells()
    else:
        parser.print_help()