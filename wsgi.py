# wsgi.py
import eventlet
eventlet.monkey_patch()  # Chamado antes de qualquer import

from run import app  # Importa o app após o monkey patch

if __name__ == "__main__":
    app.run()