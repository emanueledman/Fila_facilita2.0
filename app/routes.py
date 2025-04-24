# app/routes.py
import requests
from flask import jsonify

def init_routes(app):
    @app.route('/api/status', methods=['GET'])
    def status():
        return jsonify({'message': 'API do Facilita 2.0 está funcionando!'})
    
    @app.route('/', methods=['GET'])
    def home():
        return jsonify({'message': 'Bem-vindo à API do Facilita 2.0! Use /api/status para verificar o status ou /api/queues para listar filas.'})
    
    @app.route('/get-my-ip', methods=['GET'])
    def get_my_ip():
        try:
            ip = requests.get('https://api.ipify.org').text
            return jsonify({'ip': ip})
        except Exception as e:
            return jsonify({'error': f'Erro ao obter IP: {str(e)}'})
