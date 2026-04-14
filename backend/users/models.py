from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Custom user: email as main identifier, first_name/last_name for profile."""
    class SubscriptionPlan(models.TextChoices):
        FREE = 'free', 'Free'
        MONTHLY = 'monthly', 'Monthly'
        YEARLY = 'yearly', 'Yearly'

    email = models.EmailField('email address', unique=True)
    subscription_plan = models.CharField(
        max_length=20,
        choices=SubscriptionPlan.choices,
        default=SubscriptionPlan.FREE,
    )
    subscription_started_at = models.DateTimeField(null=True, blank=True)
    subscription_ends_at = models.DateTimeField(null=True, blank=True)
    subscription_auto_renew = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users_user'
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def __str__(self):
        return self.email


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_transactions',
    )
    plan = models.CharField(max_length=20, choices=User.SubscriptionPlan.choices)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUCCEEDED,
    )
    card_last4 = models.CharField(max_length=4)
    card_brand = models.CharField(max_length=24, blank=True)
    cardholder_name = models.CharField(max_length=255, blank=True)
    external_reference = models.CharField(max_length=64, unique=True)
    paid_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'users_payment_transaction'
        ordering = ['-paid_at']

    def __str__(self):
        return f'{self.user.email} {self.plan} {self.amount} {self.currency}'
