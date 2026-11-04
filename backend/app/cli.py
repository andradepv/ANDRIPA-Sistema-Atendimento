"""Comandos administrativos.

    python -m app.cli bootstrap --establishment "Bar do Zé" --tz America/Manaus \
        --admin-name "Ana" --admin-email ana@exemplo.com            (senha lida do terminal ou de ANDRIPA_BOOTSTRAP_PASSWORD)
    python -m app.cli seed-dev                                       (apenas ambiente de desenvolvimento)
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.permissions import Role
from app.core.security import hash_secret, new_public_code
from app.db.session import db
from app.models import DiningTable, Establishment, User


def _password(prompt: str) -> str:
    pw = os.environ.get("ANDRIPA_BOOTSTRAP_PASSWORD") or getpass.getpass(prompt)
    if len(pw) < 10:
        sys.exit("A senha precisa ter pelo menos 10 caracteres.")
    return pw


async def bootstrap(args: argparse.Namespace) -> None:
    s = get_settings()
    db.init(s.database_url, null_pool=True)
    async with db.session() as session:
        if (await session.execute(select(User).where(User.email == args.admin_email.lower()))).scalar_one_or_none():
            sys.exit("Já existe um usuário com esse e-mail.")
        est = Establishment(name=args.establishment, timezone=args.tz)
        session.add(est)
        await session.flush()
        session.add(User(establishment_id=est.id, name=args.admin_name, email=args.admin_email.lower(),
                         role=Role.ADMIN, password_hash=hash_secret(_password("Senha do administrador: "))))
        for n in range(1, args.tables + 1):
            session.add(DiningTable(establishment_id=est.id, number=n, public_code=new_public_code()))
        await session.commit()
        print(f"Estabelecimento criado: {est.id} com {args.tables} mesas.")
    await db.dispose()


async def seed_dev(_: argparse.Namespace) -> None:
    """Dados de DEMONSTRAÇÃO para desenvolvimento local. Recusa rodar em produção/homologação."""
    s = get_settings()
    if s.environment not in ("development", "test"):
        sys.exit("seed-dev só pode ser executado em development/test.")
    db.init(s.database_url, null_pool=True)
    async with db.session() as session:
        if (await session.execute(select(Establishment).limit(1))).scalar_one_or_none():
            print("Banco já possui dados; seed ignorado.")
            return
        est = Establishment(name="Bar Demonstração", timezone="America/Manaus")
        session.add(est)
        await session.flush()
        pw = os.environ.get("ANDRIPA_DEV_PASSWORD", "trocar-esta-senha")
        for name, email, role, pin in (("Admin Demo", "admin@demo.local", Role.ADMIN, "1111"),
                                       ("Caixa Demo", "caixa@demo.local", Role.CAIXA, "2222"),
                                       ("Atendente Demo", "atendente@demo.local", Role.ATENDENTE, "3333")):
            session.add(User(establishment_id=est.id, name=name, email=email, role=role,
                             password_hash=hash_secret(pw), pin_hash=hash_secret(pin)))
        for n in range(1, 9):
            session.add(DiningTable(establishment_id=est.id, number=n, public_code=new_public_code()))
        await session.commit()
        print("Seed de demonstração criado. Usuários: admin@demo.local, caixa@demo.local, atendente@demo.local")
        print("Senha: valor de ANDRIPA_DEV_PASSWORD (padrão de desenvolvimento documentado no README).")
    await db.dispose()


def main() -> None:
    p = argparse.ArgumentParser(prog="andripa")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    b.add_argument("--establishment", required=True)
    b.add_argument("--tz", default="America/Sao_Paulo")
    b.add_argument("--admin-name", required=True)
    b.add_argument("--admin-email", required=True)
    b.add_argument("--tables", type=int, default=10)
    sub.add_parser("seed-dev")
    args = p.parse_args()
    if args.cmd == "bootstrap":
        asyncio.run(bootstrap(args))
    else:
        asyncio.run(seed_dev(args))


if __name__ == "__main__":
    main()
