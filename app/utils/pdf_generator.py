from venv import logger
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.barcode.qr import QrCodeWidget
from svglib.svglib import svg2rlg
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont




import io
from datetime import datetime

def generate_ticket_pdf(ticket, institution_name, service, position, wait_time):
    """
    Gera um PDF para um ticket físico com o layout da imagem fornecida.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    
    # Configurações de layout
    width, height = A4
    margin = 20 * mm
    center_x = width / 2
    
    # Título: "Sua senha"
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(center_x, height - margin - 20, "Sua senha")
    
    # Nome da instituição
    c.setFont("Helvetica", 14)
    c.drawCentredString(center_x, height - margin - 40, institution_name)
    
    # "Número da senha"
    c.setFont("Helvetica", 12)
    c.drawCentredString(center_x, height - margin - 60, "Número da senha")
    
    # Número da senha (ex.: B1)
    c.setFont("Helvetica-Bold", 40)
    c.drawCentredString(center_x, height - margin - 90, f"{ticket.queue.prefix}{ticket.ticket_number}")
    
    # QR Code
    qr = QrCodeWidget(ticket.qr_code)
    d = Drawing(100, 100)
    d.add(qr)
    renderPDF.draw(d, c, center_x - 50, height - margin - 190)
    
    # Balcão (guichê)
    c.setFont("Helvetica", 12)
    counter_text = f"Balcão: {ticket.counter if ticket.counter else 'Aguardando chamada'}"
    c.drawCentredString(center_x, height - margin - 210, counter_text)
    
    # Posição e Tempo de espera
    c.setFont("Helvetica", 12)
    c.drawCentredString(center_x, height - margin - 230, f"Posição: {position}")
    c.drawCentredString(center_x, height - margin - 250, f"Tempo de espera: {wait_time} minutos")
    
    # Data de emissão e expiração
    c.setFont("Helvetica", 10)
    c.drawCentredString(center_x, height - margin - 270, f"Data de Emissão: {ticket.issued_at.strftime('%d/%m/%Y %H:%M')}")
    if ticket.expires_at:
        c.drawCentredString(center_x, height - margin - 290, f"Expira em: {ticket.expires_at.strftime('%d/%m/%Y %H:%M')}")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer



def generate_physical_ticket_pdf(ticket, position):
    """
    Gera um PDF para um ticket físico emitido via totem.
    Implementação melhorada para evitar erros com QR code e fontes não disponíveis.
    """
    try:
        buffer = io.BytesIO()
        # Configurações de layout
        width, height = A4
        margin = 20 * mm
        center_x = width / 2
        
        # Iniciar canvas - importante verificar quais fontes estão disponíveis
        c = canvas.Canvas(buffer, pagesize=A4)
        
        # Fontes base padrão do ReportLab que estão sempre disponíveis:
        # - Helvetica (normal, bold, oblique)
        # - Times-Roman (normal, bold, italic)
        # - Courier (normal, bold, oblique)
        # - Symbol
        # - ZapfDingbats
        
        # Validar informações da fila
        queue = ticket.queue
        if not queue:
            logger.error(f"Relação ticket.queue não carregada para ticket {ticket.id}")
            raise ValueError("Fila associada ao ticket não encontrada")
        
        # Registrar informações para depuração
        logger.info(f"Gerando PDF para ticket {ticket.id} com prefix={queue.prefix}")
        
        # Preparar dados para o documento
        service_name = queue.service.name if queue.service else "Desconhecido"
        department_name = queue.department.name if queue.department else "Desconhecido"
        branch_name = queue.department.branch.name if queue.department and queue.department.branch else "Desconhecido"
        institution_name = (
            queue.department.branch.institution.name
            if queue.department and queue.department.branch and queue.department.branch.institution
            else "Desconhecido"
        )
        
        # Título: "Sua senha"
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(center_x, height - margin - 20, "Sua senha")
        
        # Nome da instituição
        c.setFont("Helvetica", 14)
        c.drawCentredString(center_x, height - margin - 40, institution_name)
        
        # Nome da filial/departamento (informação adicional)
        c.setFont("Helvetica", 12)
        c.drawCentredString(center_x, height - margin - 60, f"{branch_name} - {department_name}")
        
        # Serviço
        c.setFont("Helvetica", 12)
        c.drawCentredString(center_x, height - margin - 80, f"Serviço: {service_name}")
        
        # Número da senha (ex.: BI123)
        c.setFont("Helvetica-Bold", 40)
        ticket_id = f"{queue.prefix}{ticket.ticket_number}"
        c.drawCentredString(center_x, height - margin - 120, ticket_id)
        
        # Gerar QR Code de forma segura
        try:
            # Criar o QR code diretamente sem depender do svg2rlg
            qr_code = QrCodeWidget(ticket.qr_code)
            qr_code.barWidth = 120
            qr_code.barHeight = 120
            qr_code.qrVersion = 3  # Versão que comporta o tamanho do conteúdo
            
            # Criar drawing com tamanho definido
            d = Drawing(140, 140)
            d.add(qr_code)
            d.renderScale = 1  # Definir explicitamente a escala
            
            # Posicionar e desenhar o QR code
            renderPDF.draw(d, c, center_x - 70, height - margin - 260)
            
        except Exception as e:
            # Em caso de falha no QR code, registrar o erro e continuar sem o QR
            logger.error(f"Erro ao gerar QR code para ticket {ticket.id}: {str(e)}")
            c.setFont("Helvetica", 10)
            c.drawCentredString(center_x, height - margin - 200, "QR Code indisponível")
        
        # Balcão (guichê)
        c.setFont("Helvetica", 14)
        counter_text = f"Balcão: {ticket.counter if ticket.counter else 'Aguardando chamada'}"
        c.drawCentredString(center_x, height - margin - 290, counter_text)
        
        # Posição
        c.setFont("Helvetica", 14)
        c.drawCentredString(center_x, height - margin - 310, f"Posição: {position}")
        
        # Data de emissão e expiração
        c.setFont("Helvetica", 10)
        issued_date = ticket.issued_at.strftime('%d/%m/%Y %H:%M') if ticket.issued_at else "N/A"
        c.drawCentredString(center_x, height - margin - 330, f"Data de Emissão: {issued_date}")
        
        if ticket.expires_at:
            expiry_date = ticket.expires_at.strftime('%d/%m/%Y %H:%M')
            c.drawCentredString(center_x, height - margin - 350, f"Expira em: {expiry_date}")
        
        # Adicionar linha separadora no rodapé
        c.line(margin, margin + 30, width - margin, margin + 30)
        
        # Adicionar mensagem de rodapé (usando Helvetica padrão em vez de Helvetica-Italic)
        c.setFont("Helvetica", 9)
        c.drawCentredString(center_x, margin + 15, "Obrigado pela preferência")
        
        # Finalizar página e salvar o documento
        c.showPage()
        c.save()
        
        # Retornar o buffer com o PDF
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        logger.error(f"Erro ao gerar PDF para ticket {ticket.id if ticket else 'desconhecido'}: {str(e)}")
        raise