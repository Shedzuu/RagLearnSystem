from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user: email as main identifier, first_name/last_name for profile."""
    email = models.EmailField('email address', unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users_user'
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def __str__(self):
        return self.email
