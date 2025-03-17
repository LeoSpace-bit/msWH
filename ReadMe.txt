alembic init alembic
python commands.py init
python commands.py cell
python commands.py revision -m "init"
python command.py migrate



StorageLocations:
id PK
название сектора (строка длина 50 символов) Уникальный
вместимость (количество ячеек [n], >0)

StockAllocation:
StorageLocation_id PK
cell_id PK
StockItems_id NOT NULL
Проверка: cell_id между 1 и [n]
);

StockItems:
pgd_id PK
количество (>= 0)

Invoices:
id PK
тип_счета ('arrival', 'departure', 'write-off', name='invoice_type')
статус ('rejected', 'error', 'completed', 'created', 'shipping', 'received', name='invoice_status')
дата_создания
склад_отправителя (строка длинной 24 символа)
склад_получателя (строка длинной 24 символа)

InvoiceItems:
id_invoice PK
id_pgd_id PK
количество (>0)
номер_партии
batch_number (строка длина 50 символов)
дата_производства
дата_истечения