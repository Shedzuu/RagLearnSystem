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
    google_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
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


class EmailVerificationCode(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='email_verification_codes',
    )
    code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users_email_verification_code'
        ordering = ['-created_at']

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self):
        return self.consumed_at is not None

    def __str__(self):
        return f'{self.user.email} ({self.code})'
