"""Cadastro inicial da equipe. A senha é solicitada sem aparecer no terminal."""

import argparse
from getpass import getpass

from .authentication import create_user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Nome exibido no menu")
    parser.add_argument("--reset-password", action="store_true", help="Redefine a senha de uma conta existente e invalida suas sessões")
    args = parser.parse_args()
    password = getpass("Senha (mínimo de 12 caracteres): ")
    if password != getpass("Confirme a senha: "):
        parser.error("As senhas não coincidem")
    from .firebase_db import db
    try:
        user = create_user(db, args.email, args.name, password, reset=args.reset_password)
    except ValueError as error:
        parser.error(str(error))
    print(f"Conta pronta para acesso: {user['email']}")


if __name__ == "__main__":
    main()
