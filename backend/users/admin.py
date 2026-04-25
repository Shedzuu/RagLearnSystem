from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import PaymentTransaction, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'subscription_plan', 'is_staff')
    list_filter = ('subscription_plan', 'is_staff', 'is_superuser')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal', {'fields': ('first_name', 'last_name')}),
        (
            'Subscription',
            {
                'fields': (
                    'subscription_plan',
                    'subscription_started_at',
                    'subscription_ends_at',
                    'subscription_auto_renew',
                )
            },
        ),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {'fields': ('email', 'password1', 'password2')}),
        ('Personal', {'fields': ('first_name', 'last_name')}),
    )


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'amount', 'currency', 'status', 'card_last4', 'paid_at')
    list_filter = ('plan', 'status', 'currency')
    search_fields = ('user__email', 'external_reference', 'card_last4')
    ordering = ('-paid_at',)
