import eventlet
eventlet.monkey_patch()
from app import create_app, socketio

app = create_app()

# Não adicione nenhum código de execução direta aqui
# O Gunicorn usará a variável "app" diretamente