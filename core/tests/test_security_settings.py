from django.conf import settings
from django.test import SimpleTestCase


class SecurityMiddlewareTests(SimpleTestCase):
    def test_security_middleware_installed_first(self):
        self.assertEqual(
            settings.MIDDLEWARE[0],
            "django.middleware.security.SecurityMiddleware",
        )
        self.assertIn(
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
            settings.MIDDLEWARE,
        )

    def test_debug_defaults_insecure_cookies_for_local_dev(self):
        if settings.DEBUG:
            self.assertFalse(settings.SECURE_SSL_REDIRECT)
            self.assertFalse(settings.SESSION_COOKIE_SECURE)
            self.assertFalse(settings.CSRF_COOKIE_SECURE)
            self.assertEqual(settings.SECURE_HSTS_SECONDS, 0)

    def test_x_frame_options_deny(self):
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")

    def test_content_type_nosniff_enabled(self):
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
