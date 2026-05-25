from django.contrib.auth import get_user_model
from django.urls import reverse
from ninja import ModelSchema

User = get_user_model()


class UserSchema(ModelSchema):
    url: str

    class Meta:
        model = User
        fields = ["email"]

    @staticmethod
    def resolve_url(obj: User):
        return reverse("api:retrieve_user", kwargs={"pk": obj.pk})
