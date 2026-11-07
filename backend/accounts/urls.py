from django.urls import path

from accounts.views import LoginView, LogoutView, MeView, UserDetailView, UserListCreateView

urlpatterns = [
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("me/", MeView.as_view()),
    path("users/", UserListCreateView.as_view()),
    path("users/<int:user_id>/", UserDetailView.as_view()),
]
