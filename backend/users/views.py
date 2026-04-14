import secrets
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import EmailVerificationCode, User
from .serializers import (
    GoogleAuthSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    SubscriptionUpdateSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)


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
        user = User.objects.filter(email=val.strip().lower()).first()
        if user and not user.is_active:
            raise serializers.ValidationError(
                {'detail': 'Please verify your email before signing in.'}
            )
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

    @staticmethod
    def _generate_code():
        return ''.join(secrets.choice('0123456789') for _ in range(6))

    @classmethod
    def _issue_verification_code(cls, user):
        EmailVerificationCode.objects.filter(
            user=user,
            consumed_at__isnull=True,
        ).delete()
        verification = EmailVerificationCode.objects.create(
            user=user,
            code=cls._generate_code(),
            expires_at=timezone.now() + timedelta(minutes=settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES),
        )
        return verification

    @staticmethod
    def _send_verification_email(user, verification):
        send_mail(
            subject='Confirm your email',
            message=(
                f'Hello {user.first_name or user.email},\n\n'
                f'Your verification code is: {verification.code}\n'
                f'This code expires in {settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES} minutes.\n\n'
                'If you did not create this account, you can ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        verification = self._issue_verification_code(user)
        self._send_verification_email(user, verification)
        return Response(
            {
                'detail': 'Verification code sent to your email.',
                'email': user.email,
            },
            status=201,
        )


class VerifyEmailView(NoAuthMixin, APIView):
    permission_classes = (AllowAny,)
    serializer_class = VerifyEmailSerializer

    @staticmethod
    def _issue_tokens(user):
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email'].strip().lower()
        code = serializer.validated_data['code'].strip()
        user = User.objects.filter(email=email).first()
        if not user:
            raise serializers.ValidationError({'detail': 'Account not found.'})
        if user.is_active:
            raise serializers.ValidationError({'detail': 'This email is already verified.'})

        verification = EmailVerificationCode.objects.filter(
            user=user,
            code=code,
            consumed_at__isnull=True,
        ).first()
        if not verification:
            raise serializers.ValidationError({'detail': 'Invalid verification code.'})
        if verification.is_expired:
            raise serializers.ValidationError({'detail': 'Verification code has expired.'})

        verification.consumed_at = timezone.now()
        verification.save(update_fields=['consumed_at'])
        user.is_active = True
        user.save(update_fields=['is_active'])
        EmailVerificationCode.objects.filter(
            user=user,
            consumed_at__isnull=True,
        ).delete()
        return Response(self._issue_tokens(user))


class ResendVerificationView(NoAuthMixin, APIView):
    permission_classes = (AllowAny,)
    serializer_class = ResendVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email'].strip().lower()
        user = User.objects.filter(email=email).first()
        if not user:
            raise serializers.ValidationError({'detail': 'Account not found.'})
        if user.is_active:
            raise serializers.ValidationError({'detail': 'This email is already verified.'})

        verification = RegisterView._issue_verification_code(user)
        RegisterView._send_verification_email(user, verification)
        return Response({'detail': 'A new verification code was sent.'})


class GoogleAuthView(NoAuthMixin, APIView):
    permission_classes = (AllowAny,)
    serializer_class = GoogleAuthSerializer

    @staticmethod
    def _issue_tokens(user):
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

    @staticmethod
    def _build_username(email):
        base = (email or 'google-user').strip().lower()
        candidate = base
        suffix = 1
        while User.objects.filter(username=candidate).exists():
            suffix += 1
            candidate = f'{base}-{suffix}'
        return candidate

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_id = settings.GOOGLE_OAUTH_CLIENT_ID.strip()
        if not client_id:
            raise serializers.ValidationError(
                {'detail': 'Google sign-in is not configured on the server.'}
            )

        try:
            payload = id_token.verify_oauth2_token(
                serializer.validated_data['credential'],
                google_requests.Request(),
                client_id,
            )
        except ValueError as exc:
            raise serializers.ValidationError(
                {'detail': 'Google token validation failed.'}
            ) from exc

        if payload.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}:
            raise serializers.ValidationError({'detail': 'Invalid Google token issuer.'})
        if not payload.get('email_verified'):
            raise serializers.ValidationError({'detail': 'Google email is not verified.'})

        email = (payload.get('email') or '').strip().lower()
        google_subject = (payload.get('sub') or '').strip()
        if not email or not google_subject:
            raise serializers.ValidationError({'detail': 'Incomplete Google profile data.'})

        first_name = (payload.get('given_name') or '').strip()
        last_name = (payload.get('family_name') or '').strip()

        existing_by_subject = User.objects.filter(google_subject=google_subject).first()
        existing_by_email = User.objects.filter(email=email).first()

        if existing_by_subject and existing_by_email and existing_by_subject.pk != existing_by_email.pk:
            raise serializers.ValidationError(
                {'detail': 'This Google account is already linked to another user.'}
            )

        user = existing_by_subject or existing_by_email
        if user and user.google_subject and user.google_subject != google_subject:
            raise serializers.ValidationError(
                {'detail': 'This email is already linked to another Google account.'}
            )

        if user is None:
            try:
                with transaction.atomic():
                    user = User(
                        email=email,
                        username=self._build_username(email),
                        first_name=first_name,
                        last_name=last_name,
                        google_subject=google_subject,
                    )
                    user.set_unusable_password()
                    user.save()
            except IntegrityError as exc:
                raise serializers.ValidationError(
                    {'detail': 'Could not create a user for this Google account.'}
                ) from exc
        else:
            updated_fields = []
            if not user.google_subject:
                user.google_subject = google_subject
                updated_fields.append('google_subject')
            if first_name and not user.first_name:
                user.first_name = first_name
                updated_fields.append('first_name')
            if last_name and not user.last_name:
                user.last_name = last_name
                updated_fields.append('last_name')
            if updated_fields:
                user.save(update_fields=updated_fields)

        return Response(self._issue_tokens(user))


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
