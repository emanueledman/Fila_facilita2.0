import logging
from flask_socketio import emit

logger = logging.getLogger(__name__)

def emit_dashboard_update(socketio, branch_id, queue_id, event_type, data):
    """Emite atualização para o dashboard da filial."""
    try:
        socketio.emit(event_type, data, room=f'branch_{branch_id}', namespace='/branch_admin')
        logger.info(f"Evento {event_type} emitido para branch_id={branch_id}, queue_id={queue_id}")
    except Exception as e:
        logger.error(f"Erro ao emitir evento {event_type}: {str(e)}")

def emit_display_update(socketio, branch_id, event_type, data):
    """Emite atualização para a tela do totem."""
    try:
        socketio.emit('display_updated', {
            'branch_id': branch_id,
            'event_type': event_type,
            'data': data
        }, room=f'display_{branch_id}', namespace='/display')
        logger.info(f"Atualização de tela emitida: branch_id={branch_id}, event_type={event_type}")
    except Exception as e:
        logger.error(f"Erro ao emitir atualização de tela: {str(e)}")