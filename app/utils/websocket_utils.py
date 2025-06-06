import logging
from flask_socketio import SocketIO, emit, join_room, leave_room, ConnectionRefusedError
from flask import request
from ..models import User, Queue, Ticket
from redis import Redis
from .. import db, socketio, redis_client
import firebase_admin
from firebase_admin import auth, credentials
import os
import json

# Configurar logging
logger = logging.getLogger(__name__)

# Inicializar Firebase Admin SDK usando FIREBASE_CREDENTIALS
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(json.loads(os.getenv('FIREBASE_CREDENTIALS')))
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin SDK: {str(e)}")
        raise

# Funções de emissão de eventos
def emit_dashboard_update(socketio: SocketIO, institution_id: str = None, branch_id: str = None, queue_id: str = None, event_type: str = 'dashboard_update', data: dict = {}):
    """Emite atualização para o painel da instituição ou filial."""
    try:
        room = f'branch_{branch_id}' if branch_id else str(institution_id)
        namespace = '/branch_admin' if branch_id else '/dashboard'
        socketio.emit(event_type, {
            'institution_id': institution_id,
            'branch_id': branch_id,
            'queue_id': queue_id,
            'event_type': event_type,
            'data': data
        }, room=room, namespace=namespace)
        logger.info(f"Evento {event_type} emitido para room={room}, queue_id={queue_id}")
    except Exception as e:
        logger.error(f"Erro ao emitir evento {event_type}: {str(e)}")

def emit_display_update(socketio: SocketIO, branch_id: str, event_type: str = 'display_updated', data: dict = {}):
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

def emit_ticket_update(socketio: SocketIO, redis_client: Redis, ticket: Ticket, queue_service):
    """Emite atualização de ticket para usuário, painel e tela de totem."""
    try:
        if not ticket:
            logger.warning(f"Ticket inválido fornecido")
            return

        # Preparar dados do ticket
        ticket_data = {
            'ticket_id': ticket.id,
            'queue_id': ticket.queue_id,
            'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
            'status': ticket.status,
            'priority': ticket.priority,
            'is_physical': ticket.is_physical,
            'issued_at': ticket.issued_at.isoformat(),
            'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
            'counter': ticket.counter,
            'service': ticket.queue.service.name if ticket.queue and ticket.queue.service else 'N/A',
            'institution': (ticket.queue.department.branch.institution.name 
                           if ticket.queue and ticket.queue.department and 
                           ticket.queue.department.branch and 
                           ticket.queue.department.branch.institution else 'N/A')
        }

        mensagens_status = {
            'Pendente': f"Sua senha {ticket_data['ticket_number']} está aguardando atendimento.",
            'Chamado': f"Sua senha {ticket_data['ticket_number']} foi chamada no balcão {ticket_data['counter']}. Dirija-se ao atendimento.",
            'Atendido': f"Sua senha {ticket_data['ticket_number']} foi atendida com sucesso.",
            'Cancelado': f"Sua senha {ticket_data['ticket_number']} foi cancelada."
        }
        mensagem = mensagens_status.get(ticket.status, f"Sua senha {ticket_data['ticket_number']} foi atualizada: {ticket.status}")

        # Notificação para o usuário
        if ticket.user_id and ticket.user_id != 'PRESENCIAL' and not ticket.is_physical:
            user = User.query.get(ticket.user_id)
            if not user:
                logger.warning(f"Usuário não encontrado para ticket_id={ticket.id}, user_id={ticket.user_id}")
                return

            # Throttling de notificações
            cache_key = f"notificacao:throttle:{ticket.user_id}:{ticket.id}"
            if redis_client.get(cache_key):
                logger.debug(f"Notificação suprimida para ticket_id={ticket.id} devido a throttling")
                return
            redis_client.setex(cache_key, 60, "1")

            # Enviar notificação via FCM e/ou WebSocket
            queue_service.send_notification(
                fcm_token=user.fcm_token,
                message=mensagem,
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=ticket.user_id
            )

            # Tentar enviar via WebSocket
            try:
                socketio.emit('ticket_update', {'event': 'ticket_update', 'data': ticket_data}, namespace='/queue', room=str(ticket.user_id))
                logger.info(f"Atualização de ticket emitida via WebSocket: ticket_id={ticket.id}, user_id={ticket.user_id}")
            except Exception as e:
                logger.debug(f"Usuário {ticket.user_id} não conectado ao WebSocket: {str(e)}. Notificação FCM já enviada.")

        else:
            logger.warning(f"Não é possível emitir atualização para ticket_id={ticket.id}: usuário inválido ou ticket presencial")

        # Notificação para painel e tela de totem
        branch_id = ticket.queue.department.branch_id if ticket.queue and ticket.queue.department else None
        if branch_id:
            dashboard_data = {
                'ticket_id': ticket.id,
                'ticket_number': ticket_data['ticket_number'],
                'queue_id': ticket.queue_id,
                'counter': f"Guichê {ticket.counter:02d}" if ticket.counter else 'N/A',
                'status': ticket.status,
                'service_name': ticket.queue.service.name if ticket.queue and ticket.queue.service else 'N/A'
            }
            emit_dashboard_update(socketio, branch_id=branch_id, queue_id=ticket.queue_id, event_type='ticket_updated', data=dashboard_data)
            emit_display_update(socketio, branch_id, event_type='ticket_updated', data=dashboard_data)
            logger.info(f"Ticket atualizado para painel e totem: ticket_id={ticket.id}, status={ticket.status}")
        else:
            logger.warning(f"Não foi possível emitir atualização para painel/totem: branch_id inválido para ticket_id={ticket.id}")

    except Exception as e:
        logger.error(f"Erro geral ao processar atualização de ticket_id={ticket.id}: {str(e)}")
        
# Manipuladores de conexão/desconexão
@socketio.on('connect', namespace='/queue')
def handle_queue_connect():
    """Gerencia conexão WebSocket para usuários no namespace /queue."""
    try:
        user_id = request.args.get('user_id')
        token = request.args.get('token')

        if not user_id:
            logger.warning("ID do usuário não fornecido")
            raise ConnectionRefusedError('ID do usuário inválido')

        # Verificação simplificada do token
        if not token:
            logger.warning("Token não fornecido")
            raise ConnectionRefusedError('Token não fornecido')

        # Verificar token Firebase apenas para autenticidade básica
        try:
            decoded_token = auth.verify_id_token(token)
            if decoded_token.get('uid') != user_id:
                logger.warning(f"Token UID ({decoded_token.get('uid')}) não corresponde ao user_id ({user_id})")
                raise ConnectionRefusedError('Token inválido')
        except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError) as e:
            logger.error(f"Erro no token Firebase: {str(e)}")
            raise ConnectionRefusedError('Token inválido ou expirado')
        except Exception as e:
            logger.error(f"Falha na verificação do token: {str(e)}")
            raise ConnectionRefusedError('Falha na verificação do token')

        join_room(user_id)
        logger.info(f"Usuário {user_id} conectado ao WebSocket no namespace /queue")
        emit('connection_success', {'status': 'connected', 'user_id': user_id}, namespace='/queue', room=user_id)

    except ConnectionRefusedError as e:
        logger.error(f"Conexão WebSocket /queue recusada: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Erro inesperado na conexão WebSocket /queue: {str(e)}")
        raise ConnectionRefusedError(f'Erro inesperado: {str(e)}')

@socketio.on('disconnect', namespace='/queue')
def handle_queue_disconnect():
    """Gerencia desconexão WebSocket no namespace /queue."""
    try:
        user_id = request.sid
        leave_room(user_id)
        logger.info(f"Usuário {user_id} desconectado do WebSocket no namespace /queue")
    except Exception as e:
        logger.error(f"Erro na desconexão WebSocket /queue: {str(e)}")

@socketio.on('connect', namespace='/dashboard')
def handle_dashboard_connect():
    """Gerencia conexão WebSocket para painel."""
    try:
        token = request.args.get('token') or request.headers.get('Totem-Token')
        if not token or not redis_client.get(f'totem_token:{token}'):
            logger.warning("Token inválido ou não fornecido na conexão WebSocket do painel")
            raise ConnectionRefusedError('Token inválido')

        institution_id = request.args.get('institution_id')
        if not institution_id:
            logger.warning("institution_id não fornecido")
            raise ConnectionRefusedError('institution_id não fornecido')

        join_room(str(institution_id))
        logger.info(f"Conexão ao painel WebSocket para institution_id={institution_id}")
    except Exception as e:
        logger.error(f"Erro na conexão WebSocket do painel: {str(e)}")
        raise ConnectionRefusedError('Autenticação falhou')

@socketio.on('disconnect', namespace='/dashboard')
def handle_dashboard_disconnect():
    """Gerencia desconexão WebSocket para painel."""
    try:
        user_id = request.sid
        logger.info(f"Usuário {user_id} desconectado do painel WebSocket")
    except Exception as e:
        logger.error(f"Erro na desconexão WebSocket do painel: {str(e)}")

@socketio.on('connect', namespace='/display')
def handle_display_connect():
    """Gerencia conexão WebSocket para tela de totem."""
    try:
        token = request.args.get('token') or request.headers.get('Totem-Token')
        if not token or not redis_client.get(f'totem_token:{token}'):
            logger.warning("Token inválido ou não fornecido na conexão WebSocket da tela")
            raise ConnectionRefusedError('Token inválido')

        branch_id = request.args.get('branch_id')
        if not branch_id:
            logger.warning("branch_id não fornecido")
            raise ConnectionRefusedError('branch_id não fornecido')

        join_room(f'display_{branch_id}')
        logger.info(f"Conexão à tela WebSocket para branch_id={branch_id}")
    except Exception as e:
        logger.error(f"Erro na conexão WebSocket da tela: {str(e)}")
        raise ConnectionRefusedError('Autenticação falhou')

@socketio.on('disconnect', namespace='/display')
def handle_display_disconnect():
    """Gerencia desconexão WebSocket para tela de totem."""
    try:
        user_id = request.sid
        logger.info(f"Desconexão da tela WebSocket: {user_id}")
    except Exception as e:
        logger.error(f"Erro na desconexão WebSocket da tela: {str(e)}")