import secrets
import string
import logging
import os

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('totem_token.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def generate_totem_token(length=32):
    """
    Gera um código secreto seguro para o totem.
    
    Args:
        length (int): Comprimento do token (padrão: 32 caracteres).
    
    Returns:
        str: Token gerado.
    """
    characters = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(characters) for _ in range(length))
    return token

def save_totem_token(token, env_file='.env'):
    """
    Salva o token no arquivo .env.
    
    Args:
        token (str): Token a ser salvo.
        env_file (str): Caminho do arquivo .env.
    """
    try:
        with open(env_file, 'a') as f:
            f.write(f'TOTEM_TOKEN={token}\n')
        logger.info(f"Token salvo com sucesso no arquivo {env_file}")
    except Exception as e:
        logger.error(f"Erro ao salvar token no arquivo {env_file}: {str(e)}")

def main():
    try:
        token = generate_totem_token()
        logger.info(f"Token gerado: {token}")
        save_to_env = input("Deseja salvar o token no arquivo .env? (s/n): ").strip().lower()
        if save_to_env == 's':
            env_file = input("Digite o caminho do arquivo .env (padrão: .env): ").strip() or '.env'
            save_totem_token(token, env_file)
        else:
            logger.info("Token não foi salvo no arquivo .env")
        print(f"\nToken do totem: {token}")
        print("Adicione ao .env da aplicação como TOTEM_TOKEN.")
    except Exception as e:
        logger.error(f"Erro ao gerar token: {str(e)}")
        print(f"Erro: {str(e)}")

if __name__ == "__main__":
    main()