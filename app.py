# app.py
from flask import Flask, jsonify, request
from config import Config
from models import db, LegalEntity, StockItem, Invoice, StorageLocation, StorageCell
from flask_migrate import Migrate
from services import LogisticsService, ScannersQueue, create_invoice, check_delivery

# curl -Method POST -Uri "http://localhost:5005/check_delivery" получаем то что получили, но ничего не добавляется







def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate = Migrate(app, db)

    with app.app_context():
        db.create_all()

        # Инициализация зон и ячеек
        for zone_name, settings in Config.ZONE_SETTINGS.items():
            # Создаем или получаем зону
            zone = StorageLocation.query.filter_by(zone=zone_name).first()
            if not zone:
                zone = StorageLocation(
                    zone=zone_name,
                    capacity=settings['capacity']
                )
                db.session.add(zone)
                db.session.commit()

            # Создаем недостающие ячейки
            existing_cells = StorageCell.query.filter_by(zone_id=zone.id).count()
            if existing_cells < zone.capacity:
                for cell_num in range(existing_cells + 1, zone.capacity + 1):
                    db.session.add(StorageCell(
                        zone_id=zone.id,
                        cell_number=cell_num
                    ))
                db.session.commit()

        # Исправление: Проверка существования юридических лиц
        shipper = LegalEntity.query.filter_by(tax_id="1234567890").first()
        if not shipper:
            shipper = LegalEntity(name="Test Supplier", tax_id="1234567890")
            db.session.add(shipper)

        consignee = LegalEntity.query.filter_by(tax_id="0987654321").first()
        if not consignee:
            consignee = LegalEntity(name="Test Consignee", tax_id="0987654321")
            db.session.add(consignee)

        db.session.commit()

        # Исправление: quantity=1 вместо 0 для соответствия CHECK constraint
        safe_zone = StorageLocation.query.filter_by(zone='Safe').first()
        stock_item = StockItem.query.filter_by(pgd_id=15).first()
        if not stock_item:
            stock_item = StockItem(pgd_id=15, quantity=1, location_id=safe_zone.id)
            db.session.add(stock_item)
            db.session.commit()

        ScannersQueue.start_processing(app)

    # Temporary endpoints for testing
    @app.route('/create_invoice', methods=['POST'])
    def create_invoice_route():
        data = request.get_json()  # Исправление: get_json() вместо request.json
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        required_fields = ['invoice_type', 'shipper_id', 'items']
        missing = [f for f in required_fields if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

        invoice_id = create_invoice(
            invoice_type=data['invoice_type'],
            shipper_id=data['shipper_id'],
            items_data=data['items'],
            consignee_id=data.get('consignee_id')
        )

        if invoice_id:
            return jsonify({"invoice_id": invoice_id}), 201
        else:
            return jsonify({"error": "Invoice creation failed"}), 500

    @app.route('/send_invoice/<int:invoice_id>', methods=['POST'])
    def send_invoice_route(invoice_id):
        success = LogisticsService.send_invoice(invoice_id)
        return jsonify({"success": success}), 200 if success else 400

    @app.route('/check_delivery', methods=['POST'])
    def check_delivery_route():
        count = check_delivery()
        return jsonify({"processed_invoices": count}), 200

    @app.route('/invoices', methods=['GET'])
    def get_invoices():
        invoices = Invoice.query.all()
        return jsonify([{
            "id": inv.id,
            "type": inv.invoice_type,
            "status": inv.status,
            "items_count": len(inv.items)
        } for inv in invoices]), 200

    @app.route('/stock', methods=['GET'])
    def get_stock():
        stock = StockItem.query.all()
        result = []
        for item in stock:
            # Находим все ячейки, связанные с этим StockItem
            cells = StorageCell.query.filter_by(pgd_id=item.id).all()
            locations = []
            for cell in cells:
                locations.append(f"{cell.zone.zone}/{cell.cell_number}")

            result.append({
                "id": item.id,
                "pgd_id": item.pgd_id,
                "quantity": item.quantity,
                "location": locations[0] if locations else None  # Основная ячейка
            })
        return jsonify(result), 200

    return app


if __name__ == '__main__':
    app = create_app()
    try:
        app.run(debug=True, port=5005)
    except KeyboardInterrupt:
        pass
    finally:
        ScannersQueue.stop_processing()