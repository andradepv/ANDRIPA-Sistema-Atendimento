"""Comandos administrativos.

    python -m app.cli bootstrap --establishment "Bar do Zé" --tz America/Manaus \
        --admin-name "Ana" --admin-username ana                      (PIN lido do terminal ou de ANDRIPA_BOOTSTRAP_PIN)
    python -m app.cli gen-vapid
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
from app.models import Category, DiningTable, Establishment, OptionGroup, Product, ProductOption, User
from app.services.webpush import generate_vapid_keys


def _pin(prompt: str) -> str:
    pin = os.environ.get("ANDRIPA_BOOTSTRAP_PIN") or getpass.getpass(prompt)
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        sys.exit("O PIN precisa ter de 4 a 8 números.")
    return pin


async def bootstrap(args: argparse.Namespace) -> None:
    s = get_settings()
    db.init(s.database_url, null_pool=True)
    async with db.session() as session:
        username = args.admin_username.strip().lower()
        if (await session.execute(select(User).where(User.username == username))).scalar_one_or_none():
            sys.exit("Já existe um usuário com esse nome de usuário.")
        est = Establishment(name=args.establishment, timezone=args.tz)
        session.add(est)
        await session.flush()
        session.add(
            User(
                establishment_id=est.id,
                name=args.admin_name,
                username=username,
                role=Role.ADMIN,
                pin_hash=hash_secret(_pin("PIN do administrador (4 a 8 números): ")),
            )
        )
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
        for name, username, role, pin in (
            ("Admin Demo", "admin", Role.ADMIN, "1111"),
            ("Caixa Demo", "caixa", Role.CAIXA, "2222"),
            ("Atendente Demo", "atendente", Role.ATENDENTE, "3333"),
        ):
            session.add(
                User(establishment_id=est.id, name=name, username=username, role=role, pin_hash=hash_secret(pin))
            )
        for n in range(1, 9):
            session.add(DiningTable(establishment_id=est.id, number=n, public_code=new_public_code()))
        bebidas = Category(establishment_id=est.id, name="Bebidas", position=1)
        petiscos = Category(establishment_id=est.id, name="Petiscos", position=2)
        session.add_all([bebidas, petiscos])
        await session.flush()
        session.add(
            Product(
                establishment_id=est.id, category_id=bebidas.id, name="Água mineral 500 ml", price_cents=500, position=1
            )
        )
        session.add(
            Product(
                establishment_id=est.id,
                category_id=bebidas.id,
                name="Suco de cupuaçu",
                description="Natural, 400 ml",
                price_cents=1200,
                position=2,
            )
        )
        batata = Product(
            establishment_id=est.id,
            category_id=petiscos.id,
            name="Batata frita",
            description="Porção para 2 pessoas",
            price_cents=2800,
            position=1,
        )
        g = OptionGroup(name="Molhos", min_select=0, max_select=2)
        g.options = [
            ProductOption(name="Cheddar", price_cents=400, position=1),
            ProductOption(name="Barbecue", price_cents=300, position=2),
        ]
        batata.option_groups = [g]
        session.add(batata)
        await session.commit()
        print("Seed de demonstração criado. Usuários e PINs: admin/1111, caixa/2222, atendente/3333")
    await db.dispose()


def gen_vapid(_: argparse.Namespace) -> None:
    pub, priv = generate_vapid_keys()
    print(f"ANDRIPA_VAPID_PUBLIC_KEY={pub}")
    print(f"ANDRIPA_VAPID_PRIVATE_KEY={priv}")
    print("Guarde a chave privada no AWS Secrets Manager; nunca no repositório.")


def main() -> None:
    p = argparse.ArgumentParser(prog="andripa")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    b.add_argument("--establishment", required=True)
    b.add_argument("--tz", default="America/Sao_Paulo")
    b.add_argument("--admin-name", required=True)
    b.add_argument("--admin-username", required=True)
    b.add_argument("--tables", type=int, default=10)
    sub.add_parser("seed-dev")
    sub.add_parser("gen-vapid")
    args = p.parse_args()
    if args.cmd == "bootstrap":
        asyncio.run(bootstrap(args))
    elif args.cmd == "seed-dev":
        asyncio.run(seed_dev(args))
    else:
        gen_vapid(args)


if __name__ == "__main__":
    main()
