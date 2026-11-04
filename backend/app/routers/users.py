"""Users and roles. Admins manage them. Every signed-in user can read their own role.

Roles: platform_admin manages users and reviews agents. platform_user builds and submits agents.
Admins listed in ADMIN_EMAILS keep the admin role whatever the users table says.
"""

from fastapi import APIRouter, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import Admin, DbSession, User
from app.errors import AppError
from app.models import AppUser
from app.schemas import MeOut, RoleUpdate, UserIn, UserOut

router = APIRouter(prefix="/api/v1", tags=["users"])


def _out(email: str, role: str, created_at, config_admins: set[str]) -> UserOut:
    managed = email in config_admins
    return UserOut(
        email=email,
        role="platform_admin" if managed else role,
        managed_by_config=managed,
        created_at=created_at,
    )


@router.get("/me", response_model=MeOut)
async def me(user: User) -> MeOut:
    return MeOut(email=user.email, role=user.role)


@router.get("/users", response_model=list[UserOut])
async def list_users(session: DbSession, admin: Admin) -> list[UserOut]:
    config_admins = get_settings().admin_email_set
    rows = (await session.execute(select(AppUser).order_by(AppUser.email))).scalars().all()
    listed = {row.email: _out(row.email, row.role, row.created_at, config_admins) for row in rows}
    # Admins from the settings file show up even before they have signed in.
    for email in sorted(config_admins - listed.keys()):
        listed[email] = _out(email, "platform_admin", None, config_admins)
    return list(listed.values())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def add_user(payload: UserIn, session: DbSession, admin: Admin) -> UserOut:
    email = payload.email.lower()
    row = await session.get(AppUser, email)
    if row is None:
        row = AppUser(email=email, role=payload.role)
        session.add(row)
    else:
        row.role = payload.role
    await session.commit()
    await session.refresh(row)
    return _out(row.email, row.role, row.created_at, get_settings().admin_email_set)


@router.put("/users/{email}", response_model=UserOut)
async def change_role(email: str, payload: RoleUpdate, session: DbSession, admin: Admin) -> UserOut:
    email = email.lower()
    if email == admin.email:
        raise AppError(409, "You cannot change your own role")
    config_admins = get_settings().admin_email_set
    if email in config_admins:
        raise AppError(409, "This admin is set in ADMIN_EMAILS. Change the setting to change it.")
    row = await session.get(AppUser, email)
    if row is None:
        row = AppUser(email=email, role=payload.role)
        session.add(row)
    else:
        row.role = payload.role
    await session.commit()
    await session.refresh(row)
    return _out(row.email, row.role, row.created_at, config_admins)


@router.delete("/users/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(email: str, session: DbSession, admin: Admin) -> None:
    email = email.lower()
    if email == admin.email:
        raise AppError(409, "You cannot remove yourself")
    if email in get_settings().admin_email_set:
        raise AppError(409, "This admin is set in ADMIN_EMAILS. Change the setting to remove it.")
    row = await session.get(AppUser, email)
    if row is not None:
        await session.delete(row)
        await session.commit()
