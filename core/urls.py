from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("register", views.register, name="register"),
    path("login", views.login, name="login"),
    path("logout", views.logout, name="logout"),
    path("tasks", views.tasks, name="tasks"),
    path("dashboard", views.dashboard, name="dashboard"),
]
