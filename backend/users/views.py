from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User
from .serializers import RegisterSerializer, SubscriptionUpdateSerializer, UserSerializer


class NoAuthMixin:
    """Отключаем JWT для публичных эндпоинтов — иначе невалидный токен даёт 401 до проверки прав."""
    authentication_classes = ()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Accept 'email' in request body; map to username for auth (USERNAME_FIELD=email)."""

    def get_fields(self):
        fields = super().get_fields()
        # Let client send either email or username; we'll map email -> username in validate
        fields['email'] = serializers.EmailField(required=False, write_only=True)
        if 'username' in fields:
            fields['username'].required = False
        return fields

    def validate(self, attrs):
        # Parent expects attrs[USERNAME_FIELD] = attrs['email']; we accept 'email' or 'username' as input
        val = attrs.get('email') or attrs.get('username')
        if not val:
            raise serializers.ValidationError({'email': 'Email is required.'})
        attrs['email'] = val
        if 'username' in attrs:
            del attrs['username']
        return super().validate(attrs)


class CustomTokenObtainPairView(NoAuthMixin, TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class RegisterView(NoAuthMixin, generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer

    def perform_create(self, serializer):
        user = serializer.save()
        return user


class UserMeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class SubscriptionManageView(APIView):
    serializer_class = SubscriptionUpdateSerializer
    PLAN_PRICES = {
        User.SubscriptionPlan.MONTHLY: Decimal('9.99'),
        User.SubscriptionPlan.YEARLY: Decimal('79.99'),
    }

    @staticmethod
    def _detect_card_brand(card_number):
        if card_number.startswith('4'):
            return 'Visa'
        if card_number[:2] in {'51', '52', '53', '54', '55'}:
            return 'Mastercard'
        if card_number[:2] in {'34', '37'}:
            return 'American Express'
        return 'Card'

    @staticmethod
    def _validate_payment_method(payment_method):
        if not isinstance(payment_method, dict):
            raise serializers.ValidationError(
                {'payment_method': 'Payment details are required.'}
            )

        card_number = ''.join(ch for ch in str(payment_method.get('card_number') or '') if ch.isdigit())
        cardholder_name = str(payment_method.get('cardholder_name') or '').strip()
        expiry_month = str(payment_method.get('expiry_month') or '').strip()
        expiry_year = str(payment_method.get('expiry_year') or '').strip()
        cvv = str(payment_method.get('cvv') or '').strip()

        errors = {}
        if len(card_number) < 13 or len(card_number) > 19:
            errors['card_number'] = 'Enter a valid card number.'
        if len(cardholder_name) < 2:
            errors['cardholder_name'] = 'Enter the cardholder name.'
        if not expiry_month.isdigit() or not 1 <= int(expiry_month) <= 12:
            errors['expiry_month'] = 'Enter a valid expiry month.'
        if not expiry_year.isdigit() or len(expiry_year) != 4:
            errors['expiry_year'] = 'Enter a valid expiry year.'
        if not cvv.isdigit() or len(cvv) not in {3, 4}:
            errors['cvv'] = 'Enter a valid security code.'

        if not errors and expiry_year.isdigit() and expiry_month.isdigit():
            now = timezone.now()
            year = int(expiry_year)
            month = int(expiry_month)
            if (year, month) < (now.year, now.month):
                errors['expiry_year'] = 'This card is expired.'

        if errors:
            raise serializers.ValidationError({'payment_method': errors})

        return {
            'card_number': card_number,
            'cardholder_name': cardholder_name,
            'expiry_month': expiry_month,
            'expiry_year': expiry_year,
            'cvv': cvv,
        }

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        plan = serializer.validated_data['plan']
        auto_renew = serializer.validated_data.get('auto_renew')
        payment_method = serializer.validated_data.get('payment_method')
        now = timezone.now()
        payment_required = (
            plan != User.SubscriptionPlan.FREE
            and user.subscription_plan != plan
        )

        if payment_required:
            payment_method = self._validate_payment_method(payment_method)

        user.subscription_plan = plan
        if plan == User.SubscriptionPlan.FREE:
            user.subscription_started_at = None
            user.subscription_ends_at = None
            user.subscription_auto_renew = False
        else:
            user.subscription_started_at = now
            user.subscription_ends_at = now + (
                timedelta(days=30)
                if plan == User.SubscriptionPlan.MONTHLY
                else timedelta(days=365)
            )
            user.subscription_auto_renew = (
                auto_renew if auto_renew is not None else True
            )

        user.save(
            update_fields=[
                'subscription_plan',
                'subscription_started_at',
                'subscription_ends_at',
                'subscription_auto_renew',
            ]
        )

        if payment_required:
            user.payment_transactions.create(
                plan=plan,
                amount=self.PLAN_PRICES[plan],
                currency='USD',
                status='succeeded',
                card_last4=payment_method['card_number'][-4:],
                card_brand=self._detect_card_brand(payment_method['card_number']),
                cardholder_name=payment_method['cardholder_name'],
                external_reference=uuid4().hex,
            )
        return Response(UserSerializer(user).data)
