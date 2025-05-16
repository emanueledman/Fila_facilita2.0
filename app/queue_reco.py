from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError
from . import db, socketio, redis_client
from .models import AuditLog, Institution,Branch, Queue, Ticket, User, Department, UserRole, InstitutionType, InstitutionService, ServiceCategory, ServiceTag, UserPreference, BranchSchedule, UserBehavior, NotificationLog, Weekday
from .services import QueueService
from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
import uuid
from datetime import datetime, timedelta
import io
import json

import pytz
from .recommendation_service import RecommendationService
import re
from .auth import require_auth
import logging
from sqlalchemy import and_, or_, func
from geopy.distance import geodesic
from firebase_admin import auth
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Função de notificação (fornecida)
def emit_ticket_update(ticket):
    try:
        if not ticket or not ticket.user_id or ticket.user_id == 'PRESENCIAL' or ticket.is_physical:
            logger.warning(f"Não é possível emitir atualização para ticket_id={ticket.id}: usuário inválido ou ticket presencial")
            return

        user = User.query.get(ticket.user_id)
        if not user:
            logger.warning(f"Usuário não encontrado para ticket_id={ticket.id}, user_id={ticket.user_id}")
            return

        ticket_data = {
            'ticket_id': ticket.id,
            'queue_id': ticket.queue_id,
            'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
            'status': ticket.status,
            'priority': ticket.priority,
            'is_physical': ticket.is_physical,
            'issued_at': ticket.issued_at.isoformat(),
            'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
            'counter': ticket.counter
        }

        mensagens_status = {
            'Pendente': f"Sua senha {ticket_data['ticket_number']} está aguardando atendimento.",
            'Chamado': f"Sua senha {ticket_data['ticket_number']} foi chamada no guichê {ticket_data['counter']}. Dirija-se ao atendimento.",
            'Atendido': f"Sua senha {ticket_data['ticket_number']} foi atendida com sucesso.",
            'Cancelado': f"Sua senha {ticket_data['ticket_number']} foi cancelada."
        }
        mensagem = mensagens_status.get(ticket.status, f"Sua senha {ticket_data['ticket_number']} foi atualizada: {ticket.status}")

        cache_key = f"notificacao:throttle:{ticket.user_id}:{ticket.id}"
        if redis_client.get(cache_key):
            logger.debug(f"Notificação suprimida para ticket_id={ticket.id} devido a throttling")
            return
        redis_client.setex(cache_key, 60, "1")

        QueueService.send_notification(
            fcm_token=user.fcm_token,
            message=mensagem,
            ticket_id=ticket.id,
            via_websocket=True,
            user_id=ticket.user_id
        )

        try:
            socketio.emit('ticket_update', ticket_data, namespace='/', room=str(ticket.user_id))
            logger.info(f"Atualização de ticket emitida via WebSocket: ticket_id={ticket.id}, user_id={ticket.user_id}")
        except Exception as e:
            logger.error(f"Erro ao emitir atualização WebSocket para ticket_id={ticket.id}: {str(e)}")
    except Exception as e:
        logger.error(f"Erro geral ao processar atualização de ticket_id={ticket.id}: {str(e)}")


def emit_dashboard_update(institution_id, queue_id, event_type, data):
    try:
        socketio.emit('dashboard_update', {
            'institution_id': institution_id,
            'queue_id': queue_id,
            'event_type': event_type,
            'data': data
        }, room=institution_id, namespace='/dashboard')
        logger.info(f"Atualização de painel emitida: institution_id={institution_id}, event_type={event_type}")
    except Exception as e:
        logger.error(f"Erro ao emitir atualização de painel: {str(e)}")
        

def init_queue_reco(app):
    

    
    @app.route('/api/tickets/<ticket_id>/trade', methods=['POST'])
    @require_auth
    def trade_ticket(ticket_id):
        """Realiza a troca de um ticket com outro usuário."""
        user_id = request.user_id
        data = request.get_json() or {}
        target_ticket_id = data.get('target_ticket_id')

        if not target_ticket_id:
            logger.warning(f"target_ticket_id não fornecido para troca por user_id={user_id}")
            return jsonify({'error': 'target_ticket_id é obrigatório'}), 400

        try:
            ticket = Ticket.query.get(ticket_id)
            target_ticket = Ticket.query.get(target_ticket_id)

            if not ticket or not target_ticket:
                logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}, target_ticket_id={target_ticket_id}")
                return jsonify({'error': 'Ticket não encontrado'}), 404

            if ticket.user_id != user_id:
                logger.warning(f"Usuário {user_id} não é dono do ticket {ticket_id}")
                return jsonify({'error': 'Você não é o dono deste ticket'}), 403

            if not target_ticket.trade_available:
                logger.warning(f"Ticket {target_ticket_id} não está disponível para troca")
                return jsonify({'error': 'O ticket solicitado não está disponível para troca'}), 400

            if ticket.queue_id != target_ticket.queue_id:
                logger.warning(f"Tickets de filas diferentes: ticket_id={ticket_id}, target_ticket_id={target_ticket_id}")
                return jsonify({'error': 'Os tickets devem pertencer à mesma fila'}), 400

            if ticket.status != 'Pendente' or target_ticket.status != 'Pendente':
                logger.warning(f"Tickets não estão pendentes: ticket_id={ticket_id}, target_ticket_id={target_ticket_id}")
                return jsonify({'error': 'Ambos os tickets devem estar pendentes'}), 400

            ticket.user_id, target_ticket.user_id = target_ticket.user_id, ticket.user_id
            ticket.updated_at = datetime.utcnow()
            target_ticket.updated_at = datetime.utcnow()

            db.session.commit()

            emit_ticket_update(ticket)
            emit_ticket_update(target_ticket)

            AuditLog.create(
                user_id=user_id,
                action="trade_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} trocado com {target_ticket.queue.prefix}{target_ticket.ticket_number}"
            )

            logger.info(f"Ticket trocado: {ticket.queue.prefix}{ticket.ticket_number} com {target_ticket.queue.prefix}{target_ticket.ticket_number}")
            return jsonify({
                'message': 'Troca realizada com sucesso',
                'ticket_id': ticket.id,
                'target_ticket_id': target_ticket.id
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao trocar ticket {ticket_id} com {target_ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao realizar troca de ticket'}), 500

    @app.route('/api/tickets/<ticket_id>/trade_available', methods=['PATCH'])
    @require_auth
    def toggle_trade_availability(ticket_id):
        """Alterna a disponibilidade de um ticket para troca."""
        user_id = request.user_id
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
                return jsonify({'error': 'Ticket não encontrado'}), 404

            if ticket.user_id != user_id:
                logger.warning(f"Usuário {user_id} não é dono do ticket {ticket_id}")
                return jsonify({'error': 'Você não é o dono deste ticket'}), 403

            if ticket.status != 'Pendente':
                logger.warning(f"Ticket {ticket_id} não está pendente")
                return jsonify({'error': 'O ticket deve estar pendente para alterar a disponibilidade de troca'}), 400

            ticket.trade_available = not ticket.trade_available
            db.session.commit()

            emit_ticket_update(ticket)
            AuditLog.create(
                user_id=user_id,
                action="toggle_trade_availability",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Disponibilidade de troca do ticket {ticket.queue.prefix}{ticket.ticket_number} alterada para {ticket.trade_available}"
            )

            logger.info(f"Disponibilidade de troca alterada para ticket_id={ticket_id}: {ticket.trade_available}")
            return jsonify({
                'message': f"Disponibilidade de troca {'ativada' if ticket.trade_available else 'desativada'}",
                'ticket_id': ticket.id,
                'trade_available': ticket.trade_available
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao alterar disponibilidade de troca do ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao alterar disponibilidade de troca'}), 500

    @app.route('/api/queues/<queue_id>/call', methods=['POST'])
    @require_auth
    def call_next_tic(queue_id):
        """Chama o próximo ticket de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para chamar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para chamar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        counter = data.get('counter')

        if not counter:
            logger.warning("counter é obrigatório")
            return jsonify({'error': 'counter é obrigatório'}), 400

        try:
            ticket = QueueService.call_next_ticket(queue_id, counter)
            if not ticket:
                logger.info(f"Nenhum ticket pendente para chamar na fila {queue_id}")
                return jsonify({'message': 'Nenhum ticket pendente para chamar'}), 200

            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_called',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': counter,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=user_id,
                action="call_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} chamado no guichê {counter}"
            )

            logger.info(f"Ticket chamado: {ticket.queue.prefix}{ticket.ticket_number} no guichê {counter} (queue_id={queue_id})")
            return jsonify({
                'message': 'Ticket chamado com sucesso',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': counter
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao chamar ticket'}), 500

    @app.route('/api/tickets/<ticket_id>/complete', methods=['POST'])
    @require_auth
    def complete_ticke(ticket_id):
        """Marca um ticket como atendido."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de completar ticket por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        queue = ticket.queue
        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para completar ticket na fila {queue.id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para completar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        try:
            ticket = QueueService.complete_ticket(ticket_id)
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue.id,
                event_type='ticket_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=user_id,
                action="complete_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} marcado como atendido"
            )

            logger.info(f"Ticket completado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket_id})")
            return jsonify({
                'message': 'Ticket marcado como atendido',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}"
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao completar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao completar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao completar ticket'}), 500

    @app.route('/api/user/tickets', methods=['GET'])
    @require_auth
    def get_user_tickets():
        """Retorna os tickets de um usuário."""
        user_id = request.user_id
        status = request.args.get('status')
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')

        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        cache_key = f"cache:user_tickets:{user_id}:{status}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            query = Ticket.query.filter_by(user_id=user_id)
            if status:
                query = query.filter_by(status=status)

            tickets = query.paginate(page=page, per_page=per_page, error_out=False)
            result = [
                {
                    'id': t.id,
                    'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
                    'queue_id': t.queue_id,
                    'service': t.queue.service.name,
                    'branch': t.queue.department.branch.name,
                    'institution': t.queue.department.branch.institution.name,
                    'status': t.status,
                    'priority': t.priority,
                    'is_physical': t.is_physical,
                    'trade_available': t.trade_available,
                    'issued_at': t.issued_at.isoformat(),
                    'expires_at': t.expires_at.isoformat() if t.expires_at else None,
                    'counter': t.counter,
                    'estimated_wait_time': f"{int(t.queue.estimated_wait_time)} minutos" if t.queue.estimated_wait_time else "N/A"
                } for t in tickets.items
            ]

            response = {
                'tickets': result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': tickets.total,
                    'total_pages': tickets.pages
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Tickets retornados para user_id={user_id}: {len(result)} tickets")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter tickets do usuário {user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter tickets'}), 500


    @app.route('/api/user/preferences', methods=['POST'])
    @require_auth
    def set_user_preference():
        """Define preferências do usuário."""
        user_id = request.user_id
        data = request.get_json() or {}
        institution_type_id = data.get('institution_type_id')
        institution_id = data.get('institution_id')
        service_category_id = data.get('service_category_id')
        neighborhood = data.get('neighborhood')
        is_client = data.get('is_client', False)
        is_favorite = data.get('is_favorite', False)

        if not any([institution_type_id, institution_id, service_category_id, neighborhood]):
            logger.warning(f"Dados insuficientes para definir preferência: user_id={user_id}")
            return jsonify({'error': 'Pelo menos um critério de preferência é obrigatório'}), 400

        if institution_type_id and not InstitutionType.query.get(institution_type_id):
            logger.warning(f"Tipo de instituição não encontrado: institution_type_id={institution_type_id}")
            return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
        if institution_id and not Institution.query.get(institution_id):
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        if service_category_id and not ServiceCategory.query.get(service_category_id):
            logger.warning(f"Categoria de serviço não encontrada: service_category_id={service_category_id}")
            return jsonify({'error': 'Categoria de serviço não encontrada'}), 404
        if neighborhood and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
            logger.warning(f"Bairro inválido: {neighborhood}")
            return jsonify({'error': 'Bairro inválido'}), 400

        try:
            preference = UserPreference.query.filter_by(
                user_id=user_id,
                institution_type_id=institution_type_id,
                institution_id=institution_id,
                service_category_id=service_category_id,
                neighborhood=neighborhood,
                is_client=is_client
            ).first()

            if not preference:
                preference = UserPreference(
                    user_id=user_id,
                    institution_type_id=institution_type_id,
                    institution_id=institution_id,
                    service_category_id=service_category_id,
                    neighborhood=neighborhood,
                    is_client=is_client,
                    is_favorite=is_favorite,
                    preference_score=1,
                    visit_count=0
                )
                db.session.add(preference)
            else:
                preference.is_favorite = is_favorite
                preference.preference_score += 1
                preference.updated_at = datetime.utcnow()

            db.session.commit()
            AuditLog.create(
                user_id=user_id,
                action="set_preference",
                resource_type="user_preference",
                resource_id=preference.id,
                details=f"Preferência definida: institution_type_id={institution_type_id}, institution_id={institution_id}, service_category_id={service_category_id}, neighborhood={neighborhood}"
            )

            if redis_client:
                try:
                    redis_client.delete(f"cache:user_preferences:{user_id}")
                    logger.info(f"Cache invalidado para user_preferences:{user_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Preferência definida para user_id={user_id}")
            return jsonify({'message': 'Preferência definida com sucesso', 'preference_id': preference.id}), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao definir preferência para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao definir preferência'}), 500
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao definir preferência para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao definir preferência'}), 500

    @app.route('/api/user/preferences', methods=['GET'])
    @require_auth
    def get_user_preferences():
        """Retorna as preferências do usuário."""
        user_id = request.user_id
        cache_key = f"cache:user_preferences:{user_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            preferences = UserPreference.query.filter_by(user_id=user_id).all()
            result = [
                {
                    'id': pref.id,
                    'institution_type': {
                        'id': pref.institution_type.id,
                        'name': pref.institution_type.name
                    } if pref.institution_type else None,
                    'institution': {
                        'id': pref.institution.id,
                        'name': pref.institution.name
                    } if pref.institution else None,
                    'service_category': {
                        'id': pref.service_category.id,
                        'name': pref.service_category.name
                    } if pref.service_category else None,
                    'neighborhood': pref.neighborhood,
                    'is_client': pref.is_client,
                    'is_favorite': pref.is_favorite,
                    'visit_count': pref.visit_count,
                    'last_visited': pref.last_visited.isoformat() if pref.last_visited else None,
                    'preference_score': pref.preference_score
                } for pref in preferences
            ]

            response = {'preferences': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Preferências retornadas para user_id={user_id}: {len(result)} preferências")
            return jsonify(response), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter preferências para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao obter preferências'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao obter preferências para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao obter preferências'}), 500

    @app.route('/api/user/preferences/<preference_id>', methods=['DELETE'])
    @require_auth
    def delete_user_preference(preference_id):
        """Remove uma preferência do usuário."""
        user_id = request.user_id
        preference = UserPreference.query.get(preference_id)
        if not preference:
            logger.warning(f"Preferência não encontrada: preference_id={preference_id}")
            return jsonify({'error': 'Preferência não encontrada'}), 404

        if preference.user_id != user_id:
            logger.warning(f"Tentativa não autorizada de excluir preferência {preference_id} por user_id={user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        try:
            db.session.delete(preference)
            db.session.commit()
            AuditLog.create(
                user_id=user_id,
                action="delete_preference",
                resource_type="user_preference",
                resource_id=preference_id,
                details=f"Preferência excluída: preference_id={preference_id}"
            )

            if redis_client:
                try:
                    redis_client.delete(f"cache:user_preferences:{user_id}")
                    logger.info(f"Cache invalidado para user_preferences:{user_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Preferência {preference_id} excluída para user_id={user_id}")
            return jsonify({'message': 'Preferência excluída com sucesso'}), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro no banco de dados ao excluir preferência {preference_id} para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao excluir preferência'}), 500
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao excluir preferência {preference_id} para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao excluir preferência'}), 500

    @app.route('/api/queues/totem', methods=['POST'])
    def generate_totem_ticket():
        """Gera um ticket físico via totem, com limite por IP."""
        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        client_ip = request.remote_addr

        if not queue_id:
            logger.warning("queue_id não fornecido")
            return jsonify({'error': 'queue_id é obrigatório'}), 400

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        cache_key = f"totem:throttle:{client_ip}"
        if redis_client.get(cache_key):
            logger.warning(f"Limite de emissão atingido para IP {client_ip}")
            return jsonify({'error': 'Limite de emissão atingido. Tente novamente em 30 segundos'}), 429
        redis_client.setex(cache_key, 30, "1")

        try:
            ticket, pdf_buffer = QueueService.generate_physical_ticket_for_totem(queue_id=queue_id)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_issued',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': ticket.issued_at.isoformat()
                }
            )
            logger.info(f"Ticket físico emitido via totem: {ticket.queue.prefix}{ticket.ticket_number} (IP: {client_ip})")
            return send_file(
                io.BytesIO(pdf_buffer.getvalue()),
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            logger.error(f"Erro ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao emitir ticket'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao emitir ticket via totem: {str(e)}")
            return jsonify({'error': 'Erro interno ao emitir ticket'}), 500

    @app.route('/api/services/similar/<service_id>', methods=['GET'])
    def similar_services(service_id):
        """Retorna serviços similares ao serviço especificado."""
        service = InstitutionService.query.get(service_id)
        if not service:
            logger.warning(f"Serviço não encontrado: service_id={service_id}")
            return jsonify({'error': 'Serviço não encontrado'}), 404

        user_id = request.args.get('user_id')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        limit = request.args.get('limit', '5')

        try:
            limit = int(limit)
            if limit < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"Limite inválido: {limit}")
            return jsonify({'error': 'limit deve ser um número positivo'}), 400

        if user_lat:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400

        cache_key = f"cache:similar_services:{service_id}:{user_id}:{user_lat}:{user_lon}:{limit}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            similar_service_ids = collaborative_model.get_similar_services(service_id, n=limit)
            result = []
            for sim_service_id in similar_service_ids:
                sim_service = InstitutionService.query.get(sim_service_id)
                if not sim_service:
                    continue
                queues = Queue.query.filter_by(service_id=sim_service.id).all()
                branch = queues[0].department.branch if queues else None
                distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon and branch else None
                quality_score = service_recommendation_predictor.predict_service(sim_service, user_id)
                result.append({
                    'id': sim_service.id,
                    'name': sim_service.name,
                    'institution': {
                        'id': sim_service.institution.id,
                        'name': sim_service.institution.name
                    },
                    'category': {
                        'id': sim_service.category.id,
                        'name': sim_service.category.name
                    } if sim_service.category else None,
                    'distance_km': float(distance) if distance is not None else 'Desconhecida',
                    'quality_score': float(quality_score)
                })

            response = {'service_id': service_id, 'similar_services': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Serviços similares retornados para service_id={service_id}: {len(result)} serviços")
            return jsonify(response), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter serviços similares para service_id={service_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao obter serviços similares'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao obter serviços similares para service_id={service_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao obter serviços similares'}), 500

   
  
    @app.route('/institutions/<institution_id>', methods=['GET'])
    @require_auth
    def get_institution(institution_id):
        """Retorna os detalhes de uma instituição específica."""
        try:
            logger.debug(f"Buscando instituição: {institution_id}")
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.warning(f"Instituição não encontrada: {institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            institution_type = InstitutionType.query.get(institution.institution_type_id)
            response = {
                'id': institution.id,
                'name': institution.name or 'Desconhecida',
                'type': {
                    'id': institution.institution_type_id,
                    'name': institution_type.name if institution_type else 'Desconhecido'
                },
                'description': institution.description or 'Sem descrição'
            }
            logger.debug(f"Resposta para instituição {institution_id}: {response}")
            return jsonify(response)
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao buscar instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados'}), 500
        except Exception as e:
            logger.error(f"Erro ao buscar instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
    

    @app.route('/api/tickets/trade_available', methods=['GET'])
    @require_auth
    def list_trade_available_tickets():
        """Lista tickets disponíveis para troca."""
        user_id = request.user_id
        try:
            user_tickets = Ticket.query.filter_by(user_id=user_id, status='Pendente').all()
            user_queue_ids = {t.queue_id for t in user_tickets}

            if not user_queue_ids:
                return jsonify([]), 200

            tickets = Ticket.query.filter(
                Ticket.queue_id.in_(user_queue_ids),
                Ticket.trade_available == True,
                Ticket.status == 'Pendente',
                Ticket.user_id != user_id
            ).all()

            result = []
            for t in tickets:
                wait_time = QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority)
                result.append({
                    'id': t.id,
                    'service': t.queue.service.name,
                    'institution': {
                        'name': t.queue.department.branch.institution.name,
                        'type': {
                            'id': t.queue.department.branch.institution.type.id,
                            'name': t.queue.department.branch.institution.type.name
                        }
                    },
                    'branch': t.queue.department.branch.name,
                    'number': f"{t.queue.prefix}{t.ticket_number}",
                    'position': max(0, t.ticket_number - t.queue.current_ticket),
                    'user_id': t.user_id,
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                    'quality_score': float(service_recommendation_predictor.predict(t.queue, user_id))
                })

            logger.info(f"Tickets disponíveis para troca retornados para user_id={user_id}: {len(result)} tickets")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets disponíveis para troca para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets para troca'}), 500

    @app.route('/api/ticket/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_ticket(ticket_id):
        """Cancela um ticket."""
        user_id = request.user_id
        try:
            ticket = QueueService.cancel_ticket(ticket_id, user_id)
            emit_ticket_update(ticket)
            logger.info(f"Senha cancelada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            QueueService.send_notification(
                fcm_token=User.query.get(user_id).fcm_token,
                message=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado",
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=user_id
            )
            AuditLog.create(
                user_id=user_id,
                action="cancel_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado"
            )
            return jsonify({'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao cancelar ticket'}), 500

    @app.route('/api/queues/<queue_id>/metrics', methods=['GET'])
    @require_auth
    def queue_metrics(queue_id):
        """Retorna métricas detalhadas de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar métricas por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar métricas da fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar métricas na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        cache_key = f"cache:queue_metrics:{queue_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            metrics = QueueService.get_queue_metrics(queue_id)
            response = {
                'queue_id': queue_id,
                'service': queue.service.name,
                'branch': queue.department.branch.name,
                'metrics': {
                    'total_tickets': metrics['total_tickets'],
                    'active_tickets': queue.active_tickets,
                    'avg_wait_time': f"{int(queue.avg_wait_time)} minutos" if queue.avg_wait_time else "N/A",
                    'avg_service_time': f"{int(queue.last_service_time)} minutos" if queue.last_service_time else "N/A",
                    'peak_hours': [
                        {'hour': h['hour'], 'ticket_count': h['ticket_count']}
                        for h in metrics['peak_hours']
                    ],
                    'ticket_status_distribution': metrics['ticket_status_distribution'],
                    'predicted_demand': float(demand_model.predict(queue_id, hours_ahead=1)),
                    'quality_score': float(service_recommendation_predictor.predict(queue))
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Métricas retornadas para queue_id={queue_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter métricas da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter métricas'}), 500

    @app.route('/api/queues/<queue_id>/audit', methods=['GET'])
    @require_auth
    def queue_audit(queue_id):
        """Retorna logs de auditoria para uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar auditoria por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar auditoria na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')
        action = request.args.get('action')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        if start_date:
            try:
                start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"start_date inválido: {start_date}")
                return jsonify({'error': 'Formato de start_date inválido. Use ISO 8601'}), 400
        if end_date:
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"end_date inválido: {end_date}")
                return jsonify({'error': 'Formato de end_date inválido. Use ISO 8601'}), 400

        cache_key = f"cache:queue_audit:{queue_id}:{action}:{start_date}:{end_date}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            query = AuditLog.query.filter_by(resource_id=queue_id, resource_type='queue')
            if action:
                query = query.filter_by(action=action)
            if start_date:
                query = query.filter(AuditLog.timestamp >= start_date)
            if end_date:
                query = query.filter(AuditLog.timestamp <= end_date)

            logs = query.paginate(page=page, per_page=per_page, error_out=False)
            result = [
                {
                    'id': log.id,
                    'user_id': log.user_id,
                    'action': log.action,
                    'resource_type': log.resource_type,
                    'resource_id': log.resource_id,
                    'details': log.details,
                    'timestamp': log.timestamp.isoformat()
                } for log in logs.items
            ]

            response = {
                'logs': result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': logs.total,
                    'total_pages': logs.pages
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Logs de auditoria retornados para queue_id={queue_id}: {len(result)} logs")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter logs de auditoria para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter logs de auditoria'}), 500

    @app.route('/api/queues/<queue_id>/ticket', methods=['POST'])
    @require_auth
    def generate_ticket(queue_id):
        """Gera um ticket virtual para um usuário autenticado."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Usuário não encontrado: user_id={user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        data = request.get_json() or {}
        priority = data.get('priority', 0)
        user_lat = data.get('latitude')
        user_lon = data.get('longitude')

        try:
            priority = int(priority)
            if priority < 0:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"Prioridade inválida: {priority}")
            return jsonify({'error': 'Prioridade deve ser um número inteiro não negativo'}), 400

        if user_lat:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400

        # Verificar se o usuário já possui um ticket ativo na mesma fila
        existing_ticket = Ticket.query.filter_by(
            user_id=user_id, queue_id=queue_id, status='Pendente'
        ).first()
        if existing_ticket:
            logger.warning(f"Usuário {user_id} já possui ticket ativo na fila {queue_id}")
            return jsonify({'error': 'Você já possui um ticket ativo nesta fila'}), 400

        # Verificar horário de funcionamento da filial
        branch = queue.department.branch
        schedules = BranchSchedule.query.filter_by(branch_id=branch.id).all()
        local_tz = pytz.timezone('Africa/Luanda')
        current_time = datetime.now(local_tz).time()
        current_weekday = datetime.now(local_tz).strftime('%A').upper()  # Ex.: 'TUESDAY'
        is_open = False
        for schedule in schedules:
            try:
                # Comparar o Enum Weekday com o valor mapeado
                if schedule.weekday == Weekday[current_weekday] and not schedule.is_closed:
                    if schedule.open_time <= current_time <= schedule.end_time:
                        is_open = True
                        break
            except KeyError:
                logger.error(f"Dia da semana inválido: {current_weekday}")
                continue
        if not is_open:
            logger.warning(f"Fila {queue_id} não está disponível fora do horário de funcionamento")
            return jsonify({'error': 'Fila não disponível fora do horário de funcionamento'}), 400

        try:
            # Chamar add_to_queue com queue_id
            ticket, _ = QueueService.add_to_queue(
                queue_id=queue_id,
                user_id=user_id,
                priority=priority,
                is_physical=False,
                fcm_token=user.fcm_token,
                branch_id=branch.id,
                user_lat=user_lat,
                user_lon=user_lon
            )
            db.session.commit()
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_issued',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': ticket.issued_at.isoformat()
                }
            )

            AuditLog.create(
                user_id=user_id,
                action="generate_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} gerado na fila {queue_id}"
            )

            response = {
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'queue_id': ticket.queue_id,
                'status': ticket.status,
                'priority': ticket.priority,
                'issued_at': ticket.issued_at.isoformat(),
                'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else "N/A"
            }

            logger.info(f"Ticket gerado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id}, user_id={user_id})")
            return jsonify(response), 201
        except ValueError as e:
            db.session.rollback()
            logger.error(f"Erro ao gerar ticket para queue_id={queue_id}, user_id={user_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao gerar ticket para queue_id={queue_id}, user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar ticket'}), 500


    @app.route('/api/update_fcm_token', methods=['POST'])
    @require_auth
    def update_fcm_token():
        user_id = request.user_id
        data = request.get_json()
        fcm_token = data.get('fcm_token')
        email = data.get('email')

        if not fcm_token or not email:
            logger.error(f"FCM token ou email não fornecidos por user_id={user_id}")
            return jsonify({'error': 'FCM token e email são obrigatórios'}), 400

        user = User.query.get(user_id)
        if not user:
            user = User(id=user_id, email=email, name="Usuário Desconhecido", active=True)
            db.session.add(user)
            logger.info(f"Novo usuário criado: user_id={user_id}, email={email}")
        else:
            if user.email != email:
                logger.warning(f"Email fornecido ({email}) não corresponde ao user_id={user_id}")
                return jsonify({'error': 'Email não corresponde ao usuário autenticado'}), 403
            user.fcm_token = fcm_token

        db.session.commit()
        logger.info(f"FCM token atualizado para user_id={user_id}, email={email}")
        QueueService.check_proximity_notifications(user_id, user.last_known_lat, user.last_known_lon)
        return jsonify({'message': 'FCM token atualizado com sucesso'}), 200


    @app.route('/api/ticket/<ticket_id>/validate', methods=['POST'])
    @require_auth
    def validate_ticket_by_id(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)

        # Verifica se o usuário tem permissão para validar o ticket
        if ticket.user_id != request.user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de validar ticket {ticket_id} por user_id={request.user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        data = request.get_json() or {}
        user_lat = data.get('user_lat')
        user_lon = data.get('user_lon')

        # Validação de latitude e longitude, se fornecidas
        if user_lat is not None and user_lon is not None:
            try:
                user_lat = float(user_lat)
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Latitude ou longitude inválidos: lat={user_lat}, lon={user_lon}")
                return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

        try:
            # Valida a presença usando o ticket diretamente
            ticket = QueueService.validate_presence(
                ticket_id=ticket_id,
                user_lat=user_lat,
                user_lon=user_lon
            )
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=ticket.queue.department.institution_id,
                queue_id=ticket.queue_id,
                event_type='call_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat()
                }
            )
            logger.info(f"Presença validada para ticket {ticket.id}")
            QueueService.send_fcm_notification(
                ticket.user_id,
                f"Presença validada para ticket {ticket.queue.prefix}{ticket.ticket_number}"
            )
            return jsonify({'message': 'Presença validada com sucesso', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao validar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao validar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': f'Erro ao validar ticket: {str(e)}'}), 500
    
    @app.route('/api/ticket/<ticket_id>/pdf', methods=['GET'])
    @require_auth
    def download_ticket_pdf(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != request.user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de baixar PDF do ticket {ticket_id} por user_id={request.user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        try:
            pdf_buffer = QueueService.generate_pdf_ticket(ticket)
            logger.info(f"PDF gerado para ticket {ticket_id}")
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except Exception as e:
            logger.error(f"Erro ao gerar PDF para ticket {ticket_id}: {e}")
            return jsonify({'error': 'Erro ao gerar PDF'}), 500

    @app.route('/api/recommendation/autocomplete', methods=['GET'])
    def autocomplete():
        """Sugestões de autocompletar para a barra de pesquisa."""
        try:
            query = request.args.get('query', '').strip()
            user_id = request.args.get('user_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            limit = request.args.get('limit', '10')

            if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
                logger.warning(f"Query inválida: {query}")
                return jsonify({'error': 'Query inválida'}), 400
            if user_lat:
                try:
                    user_lat = float(user_lat)
                except (ValueError, TypeError):
                    logger.warning(f"Latitude inválida: {user_lat}")
                    return jsonify({'error': 'Latitude deve ser um número'}), 400
            if user_lon:
                try:
                    user_lon = float(user_lon)
                except (ValueError, TypeError):
                    logger.warning(f"Longitude inválida: {user_lon}")
                    return jsonify({'error': 'Longitude deve ser um número'}), 400
            try:
                limit = int(limit)
                if limit < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"limit inválido: {limit}")
                return jsonify({'error': 'limit deve ser um número positivo'}), 400

            cache_key = f"cache:autocomplete:{query}:{user_id}:{user_lat}:{user_lon}:{limit}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            result = {
                'institution_types': [],
                'institutions': [],
                'services': [],
                'neighborhoods': []
            }

            if query:
                institution_types = InstitutionType.query.filter(
                    InstitutionType.name.ilike(f'%{query}%')
                ).limit(limit).all()
                result['institution_types'] = [{
                    'id': t.id,
                    'name': t.name,
                    'icon': t.icon_url if hasattr(t, 'icon_url') else 'https://www.bancobai.ao/media/1635/icones-104.png'
                } for t in institution_types]

                institutions = Institution.query.filter(
                    Institution.name.ilike(f'%{query}%')
                ).limit(limit).all()
                for inst in institutions:
                    distance = None
                    if user_lat and user_lon:
                        branches = Branch.query.filter_by(institution_id=inst.id).all()
                        distances = [
                            geodesic((user_lat, user_lon), (b.latitude, b.longitude)).km
                            for b in branches if b.latitude and b.longitude
                        ]
                        distance = min(distances) if distances else None
                    result['institutions'].append({
                        'id': inst.id,
                        'name': inst.name,
                        'type_id': inst.institution_type_id,
                        'distance_km': float(distance) if distance is not None else 'Desconhecida'
                    })

                services = RecommendationService.search_services(
                    query=query,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    max_results=limit,
                    max_distance_km=10.0
                )['services']
                result['services'] = [{
                    'queue_id': s['queue']['id'],
                    'service': s['queue']['service'],
                    'institution_id': s['institution']['id'],
                    'institution_name': s['institution']['name'],
                    'branch_id': s['queue']['branch_id'],
                    'branch_name': s['queue']['branch'],
                    'distance_km': s['queue']['distance'],
                    'wait_time': s['queue']['wait_time']
                } for s in services]

                neighborhoods = Branch.query.filter(
                    Branch.neighborhood.ilike(f'%{query}%')
                ).distinct(Branch.neighborhood).limit(limit).all()
                result['neighborhoods'] = [n.neighborhood for n in neighborhoods if n.neighborhood]

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(result, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Autocompletar retornado para query={query}: {len(result['services'])} serviços")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao gerar autocompletar: {str(e)}")
            return jsonify({'error': 'Erro ao gerar autocompletar'}), 500
        


    @app.route('/api/ticket/<ticket_id>', methods=['GET'])
    @require_auth
    def ticket_status(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != request.user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de visualizar status do ticket {ticket_id} por user_id={request.user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        queue = ticket.queue
        wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number, ticket.priority)
        return jsonify({
            'service': queue.service.name if queue.service else "Desconhecido",
            'institution': queue.department.branch.institution.name if queue.department and queue.department.branch and queue.department.branch.institution else None,
            'branch': queue.department.branch.name if queue.department and queue.department.branch else None,
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'qr_code': ticket.qr_code,
            'status': ticket.status,
            'counter': f"{ticket.counter:02d}" if ticket.counter else None,
            'position': max(0, ticket.ticket_number - queue.current_ticket),
            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
            'priority': ticket.priority,
            'is_physical': ticket.is_physical,
            'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None
        }), 200