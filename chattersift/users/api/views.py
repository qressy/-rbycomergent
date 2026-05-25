from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from ninja import Router

from chattersift.users.api.schema import UserSchema

if TYPE_CHECKING:
    from django.db.models import QuerySet

User = get_user_model()

router = Router(tags=["users"])


def _get_users_queryset(request) -> QuerySet[User]:
    return User.objects.filter(pk=request.user.pk)


@router.get("/", response=list[UserSchema])
def list_users(request):
    return _get_users_queryset(request)


@router.get("/me/", response=UserSchema)
def retrieve_current_user(request):
    return request.user


@router.get("/{pk}/", response=UserSchema)
def retrieve_user(request, pk: int):
    users_qs = _get_users_queryset(request)
    return get_object_or_404(users_qs, pk=pk)
