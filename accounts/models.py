from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .utils import normalize_nigerian_phone


class User(AbstractUser):
    email = models.EmailField(unique=True)

    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
    )

    is_verified = models.BooleanField(default=False)

    token_version = models.PositiveIntegerField(default=0)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
            ),
            models.UniqueConstraint(
                Lower("username"),
                name="accounts_user_username_ci_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()

        if self.username:
            self.username = self.username.strip().lower()

        if self.phone_number:
            self.phone_number = normalize_nigerian_phone(
                self.phone_number
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.email