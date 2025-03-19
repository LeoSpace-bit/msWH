#models.py
from sqlalchemy import Column, Integer, String, Enum, ForeignKey, CheckConstraint, Date, DateTime, PrimaryKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from enum import Enum as PyEnum
from datetime import datetime
from config import Config

Base = declarative_base()


class InvoiceType(PyEnum):
    ARRIVAL = 'arrival'
    DEPARTURE = 'departure'
    WRITE_OFF = 'write-off'


class InvoiceStatus(PyEnum):
    REJECTED = 'rejected'
    ERROR = 'error'
    COMPLETED = 'completed'
    CREATED = 'created'
    SHIPPING = 'shipping'
    RECEIVED = 'received'


class StorageLocation(Base):
    __tablename__ = 'storage_locations'

    id = Column(Integer, primary_key=True)
    sector_name = Column(String(50), unique=True, nullable=False)
    capacity = Column(Integer, CheckConstraint('capacity > 0'), nullable=False)

    allocations = relationship("StockAllocation", back_populates="location")


class StockAllocation(Base):
    __tablename__ = 'stock_allocations'
    __table_args__ = (
        PrimaryKeyConstraint('storage_location_id', 'cell_id'),
        CheckConstraint('cell_id > 0')
    )

    storage_location_id = Column(Integer, ForeignKey('storage_locations.id'))
    cell_id = Column(Integer)
    stock_item_id = Column(Integer, ForeignKey('stock_items.pgd_id'), nullable=False)

    location = relationship("StorageLocation", back_populates="allocations")
    stock_item = relationship("StockItem", back_populates="allocations")


class StockItem(Base):
    __tablename__ = 'stock_items'

    pgd_id = Column(Integer, primary_key=True)
    quantity = Column(Integer, CheckConstraint('quantity >= 0'), nullable=False)

    allocations = relationship("StockAllocation", back_populates="stock_item")


class Invoice(Base):
    __tablename__ = 'invoices'

    id = Column(Integer, primary_key=True)
    invoice_type = Column(Enum(InvoiceType), nullable=False)
    status = Column(Enum(InvoiceStatus), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    sender_warehouse = Column(String(24))
    receiver_warehouse = Column(String(24))

    items = relationship("InvoiceItem", back_populates="invoice")


class InvoiceItem(Base):
    __tablename__ = 'invoice_items'
    __table_args__ = (
        PrimaryKeyConstraint('invoice_id', 'pgd_id'),
    )

    invoice_id = Column(Integer, ForeignKey('invoices.id'))
    pgd_id = Column(Integer, ForeignKey('stock_items.pgd_id'))
    quantity = Column(Integer, CheckConstraint('quantity > 0'), nullable=False)
    batch_number = Column(String(50))
    production_date = Column(Date)
    expiration_date = Column(Date)

    invoice = relationship("Invoice", back_populates="items")
    stock_item = relationship("StockItem")