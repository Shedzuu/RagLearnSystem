from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import PaymentTransaction

User = get_user_model()


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = (
            'plan',
            'amount',
            'currency',
            'status',
            'card_last4',
            'card_brand',
            'cardholder_name',
            'external_reference',
            'paid_at',
        )
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    subscription_plan_label = serializers.CharField(
        source='get_subscription_plan_display',
        read_only=True,
    )
    latest_payment = serializers.SerializerMethodField()

    def get_latest_payment(self, obj):
        latest = obj.payment_transactions.first()
        if not latest:
            return None
        return PaymentTransactionSerializer(latest).data

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'subscription_plan',
            'subscription_plan_label',
            'subscription_started_at',
            'subscription_ends_at',
            'subscription_auto_renew',
            'latest_payment',
        )
        read_only_fields = ('id',)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'password_confirm', 'first_name', 'last_name')

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return data

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        return user


class GoogleAuthSerializer(serializers.Serializer):
    credential = serializers.CharField()


class SubscriptionUpdateSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=User.SubscriptionPlan.choices)
    auto_renew = serializers.BooleanField(required=False)
    payment_method = serializers.DictField(required=False)
