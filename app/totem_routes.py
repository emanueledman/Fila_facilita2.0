import io
from flask import jsonify, request, send_file
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from . import db, socketio, redis_client
from .models import Branch, Queue, Department, InstitutionService, ServiceCategory, BranchSchedule, Ticket, AuditLog, DisplayQueue
from .services import QueueService
from .utils.websocket_utils import emit_dashboard_update, emit_display_update
from sqlalchemy.exc import SQLAlchemyError
import logging
import json
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_totem_routes(app):
    """Inicializa rotas para totens físicos em filiais."""

    @app.route('/api/totem/branches/<branch_id>/services', methods=['GET'])
    def list_branch_services(branch_id):
        """Lista serviços disponíveis em uma filial, agrupados por categorias."""
        token = request.headers.get('Totem-Token')
        expected_token = app.config.get('TOTEM_TOKEN', 'h0gmVAmsj5kyhyVIlkZFF3lG4GJiqomF')
        if not token or token != expected_token:
            logger.warning(f"Token de totem inválido para IP {request.remote_addr}")
            return jsonify({'error': 'Token de totem inválido'}), 401

        branch = db.session.get(Branch, branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        # Verificar horário de funcionamento
        local_tz = pytz.timezone('Africa/Luanda')
        now = datetime.now(local_tz)
        weekday_str = now.strftime('%A').upper()
        try:
            from .models import Weekday
            weekday_enum = Weekday[weekday_str]
        except KeyError:
            logger.error(f"Dia da semana inválido para filial {branch_id}: {weekday_str}")
            return jsonify({'error': 'Dia da semana inválido'}), 400

        schedule = BranchSchedule.query.filter_by(
            branch_id=branch_id,
            weekday=weekday_enum,
            is_closed=False
        ).first()
        if not schedule or now.time() < schedule.open_time or now.time() > schedule.end_time:
            logger.warning(f"Filial {branch_id} está fechada ou fora do horário")
            return jsonify({'error': 'Filial está fechada ou fora do horário de funcionamento'}), 400

        # Verificar cache
        cache_key = f"totem:branch_services:{branch_id}:{weekday_str}"
        cached_result = redis_client.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit para {cache_key}")
            return jsonify(json.loads(cached_result))

        # Buscar departamentos e filas ativas
        queues = Queue.query.join(Department).join(InstitutionService).filter(
            Department.branch_id == branch_id,
            Queue.active_tickets < Queue.daily_limit
        ).options(
            joinedload(Queue.service).joinedload(InstitutionService.category)
        ).all()

        # Agrupar serviços por categoria
        categories = {}
        for queue in queues:
            service = queue.service
            category = service.category
            category_name = category.name if category else 'Outros'
            category_id = category.id if category else None

            if category_name not in categories:
                categories[category_name] = {
                    'category_id': category_id,
                    'services': []
                }

            categories[category_name]['services'].append({
                'queue_id': queue.id,
                'service_id': service.id,
                'service_name': service.name or 'Desconhecido',
                'active_tickets': queue.active_tickets or 0,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else 'Indisponível'
            })

        results = [
            {
                'category_id': cat_data['category_id'],
                'category_name': cat_name,
                'services': cat_data['services']
            }
            for cat_name, cat_data in sorted(categories.items())
        ]

        response = {
            'branch_id': branch_id,
            'categories': results,
            'total_categories': len(results),
            'message': 'Nenhum serviço disponível' if not results else 'Serviços listados com sucesso'
        }

        # Cachear resposta
        try:
            redis_client.setex(cache_key, 60, json.dumps(response, default=str))
            logger.info(f"Serviços cacheados para branch_id={branch_id}: {cache_key}")
        except Exception as e:
            logger.warning(f"Erro ao salvar cache: {e}")

        logger.info(f"Serviços listados para branch_id={branch_id}: {len(results)} categorias")
        return jsonify(response), 200

    @app.route('/api/totem/branches/<branch_id>/categories/<category_id>/services', methods=['GET'])
    def list_category_services(branch_id, category_id):
        """Lista serviços de uma categoria específica em uma filial."""
        token = request.headers.get('Totem-Token')
        expected_token = app.config.get('TOTEM_TOKEN', 'h0gmVAmsj5kyhyVIlkZFF3lG4GJiqomF')
        if not token or token != expected_token:
            logger.warning(f"Token de totem inválido para IP {request.remote_addr}")
            return jsonify({'error': 'Token de totem inválido'}), 401

        branch = db.session.get(Branch, branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        category = db.session.get(ServiceCategory, category_id)
        if not category:
            logger.warning(f"Categoria {category_id} não encontrada")
            return jsonify({'error': 'Categoria não encontrada'}), 404

        # Verificar horário de funcionamento
        local_tz = pytz.timezone('Africa/Luanda')
        now = datetime.now(local_tz)
        weekday_str = now.strftime('%A').upper()
        try:
            from .models import Weekday
            weekday_enum = Weekday[weekday_str]
        except KeyError:
            logger.error(f"Dia da semana inválido para filial {branch_id}: {weekday_str}")
            return jsonify({'error': 'Dia da semana inválido'}), 400

        schedule = BranchSchedule.query.filter_by(
            branch_id=branch_id,
            weekday=weekday_enum,
            is_closed=False
        ).first()
        if not schedule or now.time() < schedule.open_time or now.time() > schedule.end_time:
            logger.warning(f"Filial {branch_id} está fechada ou fora do horário")
            return jsonify({'error': 'Filial está fechada ou fora do horário de funcionamento'}), 400

        # Verificar cache
        cache_key = f"totem:category_services:{branch_id}:{category_id}:{weekday_str}"
        cached_result = redis_client.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit para {cache_key}")
            return jsonify(json.loads(cached_result))

        # Buscar serviços da categoria na filial
        queues = Queue.query.join(Department).join(InstitutionService).filter(
            Department.branch_id == branch_id,
            InstitutionService.category_id == category_id,
            Queue.active_tickets < Queue.daily_limit
        ).all()

        results = [
            {
                'queue_id': queue.id,
                'service_id': queue.service.id,
                'service_name': queue.service.name or 'Desconhecido',
                'active_tickets': queue.active_tickets or 0,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else 'Indisponível'
            }
            for queue in queues
        ]

        response = {
            'branch_id': branch_id,
            'category_id': category_id,
            'category_name': category.name,
            'services': results,
            'total_services': len(results),
            'message': 'Nenhum serviço encontrado nesta categoria' if not results else 'Serviços listados com sucesso'
        }

        # Cachear resposta
        try:
            redis_client.setex(cache_key, 60, json.dumps(response, default=str))
            logger.info(f"Serviços cacheados para branch_id={branch_id}, category_id={category_id}: {cache_key}")
        except Exception as e:
            logger.warning(f"Erro ao salvar cache: {e}")

        logger.info(f"Serviços listados para branch_id={branch_id}, category_id={category_id}: {len(results)} serviços")
        return jsonify(response), 200

    @app.route('/api/totem/branches/<branch_id>/services/<service_id>/ticket', methods=['POST'])
    def generate_service_totem_ticket(branch_id, service_id):
        """Gera uma senha física para um serviço específico em uma filial."""
        token = request.headers.get('Totem-Token')
        expected_token = app.config.get('TOTEM_TOKEN', 'h0gmVAmsj5kyhyVIlkZFF3lG4GJiqomF')
        if not token or token != expected_token:
            logger.warning(f"Token de totem inválido para IP {request.remote_addr}")
            return jsonify({'error': 'Token de totem inválido'}), 401

        branch = db.session.get(Branch, branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        service = db.session.get(InstitutionService, service_id)
        if not service:
            logger.warning(f"Serviço {service_id} não encontrado")
            return jsonify({'error': 'Serviço não encontrado'}), 404

        # Encontrar a fila correspondente ao serviço na filial
        queue = Queue.query.join(Department).filter(
            Queue.service_id == service_id,
            Department.branch_id == branch_id,
            Queue.active_tickets < Queue.daily_limit
        ).first()
        if not queue:
            logger.warning(f"Fila para serviço {service_id} não encontrada na filial {branch_id}")
            return jsonify({'error': 'Fila não encontrada ou limite diário atingido'}), 404

        client_ip = request.remote_addr
        cache_key = f"totem:throttle:{client_ip}"
        if redis_client.get(cache_key):
            logger.warning(f"Limite de emissão atingido para IP {client_ip}")
            return jsonify({'error': 'Limite de emissão atingido. Tente novamente em 30 segundos'}), 429
        redis_client.setex(cache_key, 30, "1")

        try:
            result = QueueService.generate_physical_ticket_for_totem(
                queue_id=queue.id,
                branch_id=branch_id,
                client_ip=client_ip
            )
            ticket = result['ticket']
            pdf_buffer = io.BytesIO(bytes.fromhex(result['pdf']))

            # Emitir atualização para o dashboard e tela
            ticket_data = {
                'ticket_id': ticket['id'],
                'ticket_number': f"{queue.prefix}{ticket['ticket_number']}",
                'queue_id': queue.id,
                'service_name': service.name,
                'timestamp': ticket['issued_at']
            }
            emit_dashboard_update(socketio, branch_id, queue.id, 'ticket_issued', ticket_data)
            emit_display_update(socketio, branch_id, 'ticket_issued', ticket_data)

            # Registrar log de auditoria
            AuditLog.create(
                user_id=None,
                action='generate_service_totem_ticket',
                resource_type='ticket',
                resource_id=ticket['id'],
                details=f"Ticket físico {queue.prefix}{ticket['ticket_number']} emitido para serviço {service.name} via totem (IP: {client_ip})"
            )

            logger.info(f"Ticket físico emitido via totem para serviço {service_id}: {queue.prefix}{ticket['ticket_number']} (IP: {client_ip})")
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"ticket_{queue.prefix}{ticket['ticket_number']}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            logger.error(f"Erro ao emitir ticket para serviço {service_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao emitir ticket para serviço {service_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao emitir ticket'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao emitir ticket para serviço {service_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao emitir ticket'}), 500

    @app.route('/api/totem/branches/<branch_id>/display_queues', methods=['GET'])
    def list_display_queues(branch_id):
        """Retorna filas ativas para exibição na tela do totem."""
        token = request.headers.get('Totem-Token')
        expected_token = app.config.get('TOTEM_TOKEN', 'h0gmVAmsj5kyhyVIlkZFF3lG4GJiqomF')
        if not token or token != expected_token:
            logger.warning(f"Token de totem inválido para IP {request.remote_addr}")
            return jsonify({'error': 'Token de totem inválido'}), 401

        branch = db.session.get(Branch, branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        # Buscar filas configuradas para exibição
        display_queues = DisplayQueue.query.filter_by(branch_id=branch_id).join(Queue).join(InstitutionService).options(
            joinedload(DisplayQueue.queue).joinedload(Queue.service)
        ).order_by(DisplayQueue.display_order.asc()).all()

        results = []
        for dq in display_queues:
            queue = dq.queue
            results.append({
                'queue_id': queue.id,
                'service_name': queue.service.name or 'Desconhecido',
                'current_ticket': f"{queue.prefix}{queue.current_ticket}" if queue.current_ticket else 'N/A',
                'active_tickets': queue.active_tickets or 0,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else 'Indisponível',
                'display_order': dq.display_order
            })

        response = {
            'branch_id': branch_id,
            'queues': results,
            'total_queues': len(results),
            'message': 'Nenhuma fila configurada para exibição' if not results else 'Filas listadas com sucesso'
        }

        logger.info(f"Filas de exibição retornadas para branch_id={branch_id}: {len(results)} filas")
        return jsonify(response), 200