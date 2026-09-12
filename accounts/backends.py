from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveEmailBackend(ModelBackend):
    def authenticate(
        self,
        request,
        username=None,
        password=None,
        **kwargs,
    ):
        UserModel = get_user_model()

        email = kwargs.get(
            UserModel.USERNAME_FIELD,
            username,
        )

        if not email or not password:
            return None

        try:
            user = UserModel.objects.get(
                email__iexact=email.strip()
            )
        except UserModel.DoesNotExist:
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None