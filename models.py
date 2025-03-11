#models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint

db = SQLAlchemy()


class LegalEntity(db.Model):
    __tablename__ = 'legal_entities'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    tax_id = db.Column(db.String(20), unique=True)  # ИНН


class StorageLocation(db.Model):
    __tablename__ = 'storage_locations'
    id = db.Column(db.Integer, primary_key=True)
    zone = db.Column(db.String(50), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    cells = db.relationship('StorageCell', back_populates='zone')
    # Добавляем отсутствующее отношение
    stock_items = db.relationship('StockItem', back_populates='location')

class StorageCell(db.Model):
    __tablename__ = 'storage_cells'
    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('storage_locations.id'), nullable=False)
    cell_number = db.Column(db.Integer, nullable=False)
    pgd_id = db.Column(db.Integer, db.ForeignKey('stock_items.id'), nullable=True)

    # Отношения
    zone = db.relationship('StorageLocation', back_populates='cells')
    stock_item = db.relationship('StockItem', backref='cells')

class StockItem(db.Model):
    __tablename__ = 'stock_items'
    id = db.Column(db.Integer, primary_key=True)
    pgd_id = db.Column(db.Integer, unique=True, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('storage_locations.id'), nullable=False)
    location = db.relationship('StorageLocation', back_populates='stock_items')

    __table_args__ = (
        CheckConstraint('quantity > 0', name='quantity_positive'),
        {'extend_existing': True}  # Теперь это ключевые аргументы
    )


class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow())
    invoice_type = db.Column(db.Enum('arrival', 'departure', 'write-off', name='invoice_type'), nullable=False)
    status = db.Column(db.Enum('rejected', 'error', 'completed', 'created', 'shipping', 'received', name='invoice_status'), nullable=False)
    recipient_warehouse = db.Column(db.String(24), nullable=False)
    items = db.relationship('InvoiceItem', back_populates='invoice')
    shipper_id = db.Column(db.Integer, db.ForeignKey('legal_entities.id'), nullable=False)
    consignee_id = db.Column(db.Integer, db.ForeignKey('legal_entities.id'))

    shipper = db.relationship('LegalEntity', foreign_keys=[shipper_id], backref='shipped_invoices')
    consignee = db.relationship('LegalEntity', foreign_keys=[consignee_id], backref='received_invoices')


class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    production_date = db.Column(db.Date)
    expiration_date = db.Column(db.Date)
    quantity = db.Column(db.Integer, nullable=False)
    batch_number = db.Column(db.String(50), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock_items.id'), nullable=False)

    invoice = db.relationship('Invoice', back_populates='items')
    stock_item = db.relationship('StockItem', backref='invoice_items')

    __table_args__ = (
        CheckConstraint('quantity > 0', name='item_quantity_positive'),
        CheckConstraint('expiration_date >= production_date', name='valid_expiration'),
        UniqueConstraint('stock_item_id', 'batch_number', name='unique_batch_per_item'),
    )