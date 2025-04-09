# app/routes.py
from flask import jsonify

def init_routes(app):
    @app.route('/api/status', methods=['GET'])
    def status():
        return jsonify({'message': 'API do Facilita 2.0 está funcionando!'})