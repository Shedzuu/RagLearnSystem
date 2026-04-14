from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('google/', views.GoogleAuthView.as_view(), name='google_auth'),
    path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', views.UserMeView.as_view(), name='me'),
    path('subscription/', views.SubscriptionManageView.as_view(), name='subscription-manage'),
]
