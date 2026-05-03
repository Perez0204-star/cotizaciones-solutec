import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import (
    PRIMARY_PLATFORM_SLUG,
    create_platform_workspace,
    create_quote,
    create_user,
    delete_platform_workspace,
    fetch_settings,
    get_client,
    get_platform,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    init_db,
    list_platforms,
    save_client,
    update_settings,
    use_platform,
)
from app.main import app
from app.services.auth import get_recovery_code, hash_password, verify_password


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"identity": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303


class AdminFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        init_db()

    def test_admin_can_create_secondary_user(self) -> None:
        admin_username = f"admin_{uuid4().hex[:8]}"
        admin_password = "AdminSegura123!"
        create_user(
            admin_username,
            hash_password(admin_password),
            is_admin=True,
            full_name="Admin Principal",
            email=f"{admin_username}@demo.com",
        )

        client = TestClient(app)
        login(client, admin_username, admin_password)

        new_username = f"operativo_{uuid4().hex[:8]}"
        response = client.post(
            "/admin/users",
            data={
                "full_name": "Usuario Operativo",
                "email": f"{new_username}@demo.com",
                "username": new_username,
                "password": "NuevaSegura123!",
                "confirm_password": "NuevaSegura123!",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("success=user-created", response.headers["location"])
        created_user = get_user_by_username(new_username)
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user["is_admin"], 0)
        self.assertEqual(created_user["full_name"], "Usuario Operativo")

    def test_admin_can_update_user_name_and_email(self) -> None:
        admin_username = f"admin_{uuid4().hex[:8]}"
        admin_password = "AdminSegura123!"
        create_user(
            admin_username,
            hash_password(admin_password),
            is_admin=True,
            full_name="Admin Principal",
            email=f"{admin_username}@demo.com",
        )
        target_username = f"edicion_{uuid4().hex[:8]}"
        target_id = create_user(
            target_username,
            hash_password("Operativa123!"),
            is_admin=False,
            full_name="Nombre Inicial",
            email=f"{target_username}@demo.com",
        )

        client = TestClient(app)
        login(client, admin_username, admin_password)

        response = client.post(
            f"/admin/users/{target_id}/update",
            data={
                "full_name": "Nombre Actualizado",
                "email": f"actualizado_{uuid4().hex[:4]}@demo.com",
                "username": target_username,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("success=user-updated", response.headers["location"])
        updated_user = get_user_by_username(target_username)
        self.assertEqual(updated_user["full_name"], "Nombre Actualizado")

    def test_password_recovery_updates_credentials(self) -> None:
        username = f"recovery_{uuid4().hex[:8]}"
        old_password = "ViejaClave123!"
        new_password = "NuevaClave456!"
        create_user(
            username,
            hash_password(old_password),
            is_admin=True,
            full_name="Recuperacion Demo",
            email=f"{username}@demo.com",
        )

        client = TestClient(app)
        response = client.post(
            "/password-recovery",
            data={
                "identity": f"{username}@demo.com",
                "recovery_code": get_recovery_code(),
                "password": new_password,
                "confirm_password": new_password,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?recovered=1")

        login_response = client.post(
            "/login",
            data={"identity": username, "password": new_password, "next": "/"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 303)
        self.assertEqual(login_response.headers["location"], "/")

    def test_password_recovery_can_send_email_code_for_admin_user(self) -> None:
        username = f"mail_{uuid4().hex[:8]}"
        email = f"{username}@demo.com"
        create_user(
            username,
            hash_password("ClaveDemo123!"),
            is_admin=True,
            full_name="Correo Demo",
            email=email,
        )

        client = TestClient(app)
        with patch("app.main.email_delivery_enabled", return_value=True), patch(
            "app.main.generate_email_recovery_code", return_value="123456"
        ), patch("app.main.send_password_recovery_email") as sender:
            send_response = client.post(
                "/password-recovery/send-code",
                data={"identity": email},
            )

            self.assertEqual(send_response.status_code, 200)
            sender.assert_called_once()

            reset_response = client.post(
                "/password-recovery",
                data={
                    "identity": email,
                    "recovery_code": "123456",
                    "password": "NuevaClave789!",
                    "confirm_password": "NuevaClave789!",
                },
                follow_redirects=False,
            )

        self.assertEqual(reset_response.status_code, 303)
        self.assertEqual(reset_response.headers["location"], "/login?recovered=1")

    def test_non_admin_cannot_use_email_recovery(self) -> None:
        username = f"oper_{uuid4().hex[:8]}"
        email = f"{username}@demo.com"
        create_user(
            username,
            hash_password("ClaveDemo123!"),
            is_admin=False,
            full_name="Operativo Demo",
            email=email,
        )

        client = TestClient(app)
        response = client.post(
            "/password-recovery",
            data={
                "identity": email,
                "recovery_code": get_recovery_code(),
                "password": "NuevaClave789!",
                "confirm_password": "NuevaClave789!",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("solo esta disponible para administradores", response.text)

    def test_admin_can_delete_secondary_user(self) -> None:
        admin_username = f"admin_{uuid4().hex[:8]}"
        admin_password = "AdminSegura123!"
        create_user(
            admin_username,
            hash_password(admin_password),
            is_admin=True,
            full_name="Admin Principal",
            email=f"{admin_username}@demo.com",
        )
        target_username = f"borrar_{uuid4().hex[:8]}"
        target_id = create_user(
            target_username,
            hash_password("Operativa123!"),
            is_admin=False,
            full_name="Usuario Borrable",
            email=f"{target_username}@demo.com",
        )

        client = TestClient(app)
        login(client, admin_username, admin_password)

        response = client.post(f"/admin/users/{target_id}/delete", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertIn("success=user-deleted", response.headers["location"])
        self.assertIsNone(get_user_by_id(target_id))

    def test_non_admin_cannot_open_settings(self) -> None:
        username = f"user_{uuid4().hex[:8]}"
        password = "Segura789!"
        create_user(
            username,
            hash_password(password),
            is_admin=False,
            full_name="Usuario Operativo",
            email=f"{username}@demo.com",
        )

        client = TestClient(app)
        login(client, username, password)

        response = client.get("/settings")

        self.assertEqual(response.status_code, 403)
        self.assertIn("Solo un administrador", response.text)

    def test_login_page_shows_google_button_when_configured_in_settings(self) -> None:
        username = f"googlecfg_{uuid4().hex[:8]}"
        password = "Segura789!"
        create_user(
            username,
            hash_password(password),
            is_admin=True,
            full_name="Admin Google",
            email=f"{username}@demo.com",
        )
        update_settings(
            {
                "google_oauth_client_id": "demo-client-id",
                "google_oauth_client_secret": "demo-secret",
                "google_oauth_redirect_uri": "https://demo.com/auth/google/callback",
                "google_oauth_prompt": "select_account",
            }
        )

        client = TestClient(app)
        response = client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ingresar con Google", response.text)
        self.assertNotIn("GOOGLE_OAUTH_CLIENT_ID", response.text)

    def test_login_page_uses_configurable_branding(self) -> None:
        update_settings(
            {
                "org_name": "Otra Empresa Demo",
                "brand_slogan": "Soluciones conectadas para crecer",
            }
        )

        client = TestClient(app)
        response = client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Technological World", response.text)
        self.assertIn("Conectamos ideas con tecnologia", response.text)
        self.assertNotIn("Otra Empresa Demo", response.text)
        self.assertNotIn("CARLOS ANDRES PEREZ LOAIZA", response.text)

    def test_create_platform_workspace_keeps_primary_settings_intact(self) -> None:
        update_settings(
            {
                "org_name": "Plataforma Principal Demo",
                "brand_slogan": "Marca original intacta",
            }
        )

        platform_name = f"Empresa Nueva {uuid4().hex[:6]}"
        created = create_platform_workspace(
            platform_name=platform_name,
            brand_slogan="Nueva identidad comercial",
            admin_username=f"admin_{uuid4().hex[:8]}",
            admin_password_hash=hash_password("ClavePlataforma123!"),
            admin_full_name="Admin Nueva Plataforma",
            admin_email=f"nuevo_{uuid4().hex[:8]}@demo.com",
        )

        self.assertIsNotNone(get_platform(created["slug"]))
        self.assertTrue(any(platform["slug"] == created["slug"] for platform in list_platforms()))

        with use_platform(PRIMARY_PLATFORM_SLUG):
            primary_settings = fetch_settings()
        with use_platform(created["slug"]):
            secondary_settings = fetch_settings()

        self.assertEqual(primary_settings["org_name"], "Plataforma Principal Demo")
        self.assertEqual(primary_settings["brand_slogan"], "Marca original intacta")
        self.assertEqual(secondary_settings["org_name"], platform_name)
        self.assertEqual(secondary_settings["brand_slogan"], "Nueva identidad comercial")

    def test_login_page_can_switch_to_new_platform(self) -> None:
        platform_name = f"Empresa Login {uuid4().hex[:6]}"
        created = create_platform_workspace(
            platform_name=platform_name,
            brand_slogan="Acceso separado",
            admin_username=f"platform_{uuid4().hex[:8]}",
            admin_password_hash=hash_password("ClavePlataforma123!"),
            admin_full_name="Admin Login Plataforma",
            admin_email=f"login_{uuid4().hex[:8]}@demo.com",
        )

        client = TestClient(app)
        response = client.get(f"/login?platform={created['slug']}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(platform_name, response.text)
        self.assertNotIn("Crear nueva plataforma", response.text)
        self.assertNotIn('name="platform"', response.text)

    def test_login_page_defaults_to_primary_platform_without_query(self) -> None:
        update_settings(
            {
                "org_name": "Empresa Principal Visible",
                "brand_slogan": "Base inicial protegida",
            }
        )
        created = create_platform_workspace(
            platform_name=f"Empresa Alterna {uuid4().hex[:6]}",
            brand_slogan="Acceso separado",
            admin_username=f"alt_{uuid4().hex[:8]}",
            admin_password_hash=hash_password("ClavePlataforma123!"),
            admin_full_name="Admin Alterno",
            admin_email=f"alt_{uuid4().hex[:8]}@demo.com",
        )

        client = TestClient(app)
        client.cookies.set("cotizaciones_platform", created["slug"])
        response = client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Technological World", response.text)
        self.assertIn("Conectamos ideas con tecnologia", response.text)
        self.assertNotIn(created["name"], response.text)
        self.assertNotIn('name="platform"', response.text)
        self.assertNotIn("Crear nueva plataforma", response.text)

    def test_platform_creation_page_requires_admin(self) -> None:
        username = f"user_{uuid4().hex[:8]}"
        password = "Segura789!"
        create_user(
            username,
            hash_password(password),
            is_admin=False,
            full_name="Usuario Operativo",
            email=f"{username}@demo.com",
        )

        client = TestClient(app)
        response = client.get("/platforms/new", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login?next=/platforms/new", response.headers["location"])

        login(client, username, password)
        forbidden_response = client.get("/platforms/new")
        self.assertEqual(forbidden_response.status_code, 403)
        self.assertIn("Solo los administradores", forbidden_response.text)

    def test_admin_settings_shows_registered_platforms(self) -> None:
        admin_username = f"admin_{uuid4().hex[:8]}"
        admin_password = "AdminSegura123!"
        create_user(
            admin_username,
            hash_password(admin_password),
            is_admin=True,
            full_name="Admin Principal",
            email=f"{admin_username}@demo.com",
        )
        created = create_platform_workspace(
            platform_name=f"Empresa Visual {uuid4().hex[:6]}",
            brand_slogan="Plataforma secundaria visible",
            admin_username=f"visual_{uuid4().hex[:8]}",
            admin_password_hash=hash_password("ClavePlataforma123!"),
            admin_full_name="Admin Visual",
            admin_email=f"visual_{uuid4().hex[:8]}@demo.com",
        )

        client = TestClient(app)
        login(client, admin_username, admin_password)
        response = client.get("/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Empresas creadas en el sistema", response.text)
        self.assertIn(created["name"], response.text)
        self.assertIn("Correo admin", response.text)
        self.assertIn("Protegida por seguridad", response.text)

    def test_admin_can_reset_secondary_platform_admin_password(self) -> None:
        admin_username = f"admin_{uuid4().hex[:8]}"
        admin_password = "AdminSegura123!"
        create_user(
            admin_username,
            hash_password(admin_password),
            is_admin=True,
            full_name="Admin Principal",
            email=f"{admin_username}@demo.com",
        )
        platform_admin_username = f"visual_{uuid4().hex[:8]}"
        created = create_platform_workspace(
            platform_name=f"Empresa Password {uuid4().hex[:6]}",
            brand_slogan="Reseteo interno",
            admin_username=platform_admin_username,
            admin_password_hash=hash_password("ClaveAnterior123!"),
            admin_full_name="Admin Visual",
            admin_email=f"visual_{uuid4().hex[:8]}@demo.com",
        )

        client = TestClient(app)
        login(client, admin_username, admin_password)
        response = client.post(
            f"/platforms/{created['slug']}/reset-password",
            data={
                "password": "NuevaClaveInterna123!",
                "confirm_password": "NuevaClaveInterna123!",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("success=platform-password-reset", response.headers["location"])

        with use_platform(created["slug"]):
            platform_admin = get_user_by_username(platform_admin_username)

        self.assertIsNotNone(platform_admin)
        self.assertTrue(verify_password("NuevaClaveInterna123!", platform_admin["password_hash"]))
        delete_platform_workspace(created["slug"])

    def test_admin_can_delete_secondary_platform(self) -> None:
        admin_username = f"admin_{uuid4().hex[:8]}"
        admin_password = "AdminSegura123!"
        create_user(
            admin_username,
            hash_password(admin_password),
            is_admin=True,
            full_name="Admin Principal",
            email=f"{admin_username}@demo.com",
        )
        created = create_platform_workspace(
            platform_name=f"Empresa Borrable {uuid4().hex[:6]}",
            brand_slogan="Eliminar secundaria",
            admin_username=f"remove_{uuid4().hex[:8]}",
            admin_password_hash=hash_password("ClaveBorrable123!"),
            admin_full_name="Admin Borrable",
            admin_email=f"remove_{uuid4().hex[:8]}@demo.com",
        )

        client = TestClient(app)
        login(client, admin_username, admin_password)
        response = client.post(
            f"/platforms/{created['slug']}/delete",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("success=platform-deleted", response.headers["location"])
        self.assertIsNone(get_platform(created["slug"]))

    def test_google_callback_logs_in_registered_user(self) -> None:
        username = f"googleuser_{uuid4().hex[:8]}"
        email = f"{username}@demo.com"
        google_subject = f"google-subject-{uuid4().hex[:8]}"
        create_user(
            username,
            hash_password("Segura789!"),
            is_admin=False,
            full_name="Usuario Google",
            email=email,
        )
        update_settings(
            {
                "google_oauth_client_id": "demo-client-id",
                "google_oauth_client_secret": "demo-secret",
                "google_oauth_redirect_uri": "https://demo.com/auth/google/callback",
                "google_oauth_prompt": "select_account",
            }
        )

        client = TestClient(app)
        with patch("app.main.build_google_authorize_url", return_value="https://accounts.google.com/mock"):
            start_response = client.get("/auth/google/start", follow_redirects=False)

        self.assertEqual(start_response.status_code, 303)
        state = client.cookies.get("cotizaciones_google_state")
        self.assertTrue(state)

        with patch("app.main.exchange_google_code", return_value={"access_token": "demo-token"}), patch(
            "app.main.fetch_google_userinfo",
            return_value={"sub": google_subject, "email": email, "name": "Usuario Google"},
        ):
            callback_response = client.get(
                f"/auth/google/callback?state={state}&code=demo-code",
                follow_redirects=False,
            )

        self.assertEqual(callback_response.status_code, 303)
        self.assertEqual(callback_response.headers["location"], "/")
        linked_user = get_user_by_email(email)
        self.assertIsNotNone(linked_user)
        self.assertEqual(linked_user["google_subject"], google_subject)

    def test_google_callback_rejects_unregistered_email(self) -> None:
        admin_username = f"googleadmin_{uuid4().hex[:8]}"
        google_subject = f"google-subject-{uuid4().hex[:8]}"
        create_user(
            admin_username,
            hash_password("Segura789!"),
            is_admin=True,
            full_name="Admin Google",
            email=f"{admin_username}@demo.com",
        )
        update_settings(
            {
                "google_oauth_client_id": "demo-client-id",
                "google_oauth_client_secret": "demo-secret",
                "google_oauth_redirect_uri": "https://demo.com/auth/google/callback",
                "google_oauth_prompt": "select_account",
            }
        )

        client = TestClient(app)
        with patch("app.main.build_google_authorize_url", return_value="https://accounts.google.com/mock"):
            start_response = client.get("/auth/google/start", follow_redirects=False)

        self.assertEqual(start_response.status_code, 303)
        state = client.cookies.get("cotizaciones_google_state")
        self.assertTrue(state)

        with patch("app.main.exchange_google_code", return_value={"access_token": "demo-token"}), patch(
            "app.main.fetch_google_userinfo",
            return_value={"sub": google_subject, "email": "no-registrado@demo.com", "name": "No Registrado"},
        ):
            callback_response = client.get(
                f"/auth/google/callback?state={state}&code=demo-code",
                follow_redirects=False,
            )

        self.assertEqual(callback_response.status_code, 400)
        self.assertIn("no esta autorizado", callback_response.text.lower())

    def test_quotes_search_filters_results(self) -> None:
        username = f"quotes_{uuid4().hex[:8]}"
        password = "Busqueda123!"
        create_user(
            username,
            hash_password(password),
            full_name="Buscador Demo",
            email=f"{username}@demo.com",
        )

        unique_token = uuid4().hex[:6].upper()
        payload_one = {
            "title": "COTIZACION EXPLORATORIA",
            "location": f"APARTADO {unique_token}",
            "client_name": f"CLIENTE UNO {unique_token}",
            "client_email": "",
            "requested_by": "MILLER",
            "quote_date": "2026-04-16",
            "currency_code": "COP",
            "price_factor": 1,
            "price_margin_pct": 100,
            "tax_rate": 19,
            "subtotal": 1000,
            "tax_amount": 190,
            "total": 1190,
            "notes": "",
        }
        payload_two = {
            **payload_one,
            "location": f"TURBO {unique_token}",
            "client_name": f"CLIENTE DOS {unique_token}",
        }
        items = [
            {
                "source_item_id": None,
                "sku": "SKU-001",
                "description": "SERVICIO DEMO",
                "unit": "UND",
                "qty": 1,
                "cost_amount": 0,
                "base_price_unit": 1000,
                "price_unit": 1000,
                "discount_type": "PERCENT",
                "discount_value": 0,
                "line_subtotal": 1000,
                "line_discount": 0,
                "line_total": 1000,
            }
        ]
        create_quote(payload_one, items)
        create_quote(payload_two, items)

        client = TestClient(app)
        login(client, username, password)

        response = client.get(f"/quotes?q=CLIENTE+UNO+{unique_token}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"CLIENTE UNO {unique_token}", response.text)
        self.assertNotIn(f"CLIENTE DOS {unique_token}", response.text)

    def test_clients_search_filters_results(self) -> None:
        username = f"clients_{uuid4().hex[:8]}"
        password = "Busqueda123!"
        create_user(
            username,
            hash_password(password),
            full_name="Clientes Demo",
            email=f"{username}@demo.com",
        )

        unique_token = uuid4().hex[:6].upper()
        save_client(
            {
                "client_type": "BUSINESS",
                "name": f"CLIENTE UNO {unique_token}",
                "phone": "3000000001",
                "address": "APARTADO",
            }
        )
        save_client(
            {
                "client_type": "PERSONAL",
                "name": f"CLIENTE DOS {unique_token}",
                "phone": "3000000002",
                "address": "MEDELLIN",
            }
        )

        client = TestClient(app)
        login(client, username, password)

        response = client.get(f"/clients?q=CLIENTE+UNO+{unique_token}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"CLIENTE UNO {unique_token}", response.text)
        self.assertNotIn(f"CLIENTE DOS {unique_token}", response.text)

    def test_client_save_updates_existing_record(self) -> None:
        username = f"editclient_{uuid4().hex[:8]}"
        password = "Clientes123!"
        create_user(
            username,
            hash_password(password),
            full_name="Editor Clientes",
            email=f"{username}@demo.com",
        )
        client_id = save_client(
            {
                "client_type": "BUSINESS",
                "name": "Cliente Inicial",
                "phone": "3001112233",
                "address": "APARTADO",
                "document_type": "NIT",
                "document_number": "900123456",
                "email": "cliente@demo.com",
            }
        )

        client = TestClient(app)
        login(client, username, password)

        response = client.post(
            "/clients/save",
            data={
                "id": str(client_id),
                "client_type": "PERSONAL",
                "name": "Cliente Actualizado",
                "phone": "3009998877",
                "address": "MEDELLIN",
                "document_type": "CC",
                "document_number": "10203040",
                "email": "nuevo@demo.com",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("success=client-updated", response.headers["location"])
        updated_client = get_client(client_id)
        self.assertIsNotNone(updated_client)
        self.assertEqual(updated_client["name"], "Cliente Actualizado")
        self.assertEqual(updated_client["phone"], "3009998877")
        self.assertEqual(updated_client["client_type"], "PERSONAL")


if __name__ == "__main__":
    unittest.main()
