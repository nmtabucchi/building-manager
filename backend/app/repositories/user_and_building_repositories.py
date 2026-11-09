"""Repositorios de usuarios, edificios, miembros y dashboard (migración 0006)."""
from uuid import UUID

from app.domain.auth import UserAuthContext
from app.domain.entities import Building, DashboardSummary, Member, User
from app.domain.enums import BuildingRole
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository):
    async def obtener_actual(self, auth: UserAuthContext) -> User:
        row = await self._sp.call_one("sp_user_obtener_actual", {}, auth=auth, read_only=True)
        return self._one(User, row)


class BuildingRepository(BaseRepository):
    async def crear(self, auth: UserAuthContext, *, nombre: str, direccion: str, localidad: str,
                    provincia: str, informacion_general: str | None) -> Building:
        row = await self._sp.call_one("sp_building_crear", {
            "p_nombre": nombre, "p_direccion": direccion, "p_localidad": localidad,
            "p_provincia": provincia, "p_informacion_general": informacion_general,
        }, auth=auth)
        return self._one(Building, row)

    async def actualizar(self, auth: UserAuthContext, building_id: UUID, *, nombre: str, direccion: str,
                         localidad: str, provincia: str, informacion_general: str | None) -> Building:
        row = await self._sp.call_one("sp_building_actualizar", {
            "p_building_id": building_id, "p_nombre": nombre, "p_direccion": direccion,
            "p_localidad": localidad, "p_provincia": provincia, "p_informacion_general": informacion_general,
        }, auth=auth)
        return self._one(Building, row)

    async def eliminar(self, auth: UserAuthContext, building_id: UUID) -> None:
        await self._sp.call_one("sp_building_eliminar", {"p_building_id": building_id}, auth=auth)

    async def obtener_por_id(self, auth: UserAuthContext, building_id: UUID) -> Building:
        row = await self._sp.call_one(
            "sp_building_obtener_por_id", {"p_building_id": building_id}, auth=auth, read_only=True)
        return self._one(Building, row)

    async def listar_por_usuario(self, auth: UserAuthContext) -> list[Building]:
        rows = await self._sp.call("sp_building_listar_por_usuario", {}, auth=auth, read_only=True)
        return self._many(Building, rows)


class MemberRepository(BaseRepository):
    async def listar(self, auth: UserAuthContext, building_id: UUID) -> list[Member]:
        rows = await self._sp.call(
            "sp_building_usuario_listar", {"p_building_id": building_id}, auth=auth, read_only=True)
        return self._many(Member, rows)

    async def asignar(self, auth: UserAuthContext, building_id: UUID, email: str, rol: BuildingRole) -> Member:
        row = await self._sp.call_one("sp_building_usuario_asignar", {
            "p_building_id": building_id, "p_email": email, "p_rol": rol}, auth=auth)
        return self._one(Member, row)

    async def quitar(self, auth: UserAuthContext, building_id: UUID, user_id: UUID) -> None:
        await self._sp.call_one("sp_building_usuario_quitar", {
            "p_building_id": building_id, "p_user_id": user_id}, auth=auth)


class DashboardRepository(BaseRepository):
    async def resumen(self, auth: UserAuthContext) -> DashboardSummary:
        row = await self._sp.call_one("sp_dashboard_resumen", {}, auth=auth, read_only=True)
        return self._one(DashboardSummary, row)
