import json
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import error as url_error
from urllib import request as url_request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, models, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, UpdateView, CreateView, View
from django_tenants.utils import schema_context

from .forms import AddMemberForm, PlanForm, TenantCreateForm, TenantEditForm
from .models import AVAILABLE_MODULES, TENANT_EDITIONS, Client, Domain, Plan, TenantHealthCheck, TenantHealthState, TenantMembership, TenantModule
from .user_accounts import TenantUserAccountError, save_tenant_user_account


class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


def _tenant_primary_domain(tenant):
    domains = list(tenant.domains.all())
    if not domains:
        return None
    for domain in domains:
        if domain.is_primary:
            return domain.domain
    return domains[0].domain


def _probe_tenant_health(domain, *, prefer_https=True, timeout=2.5):
    schemes = ["https", "http"] if prefer_https else ["http", "https"]
    last_error = ""

    for scheme in schemes:
        url = f"{scheme}://{domain}/healthz/"
        start = time.perf_counter()
        req = url_request.Request(url, headers={"User-Agent": "KoreHealthProbe/1.0"})
        try:
            with url_request.urlopen(req, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                code = getattr(resp, "status", None) or resp.getcode()

            payload = {}
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                payload = {}

            status_value = str(payload.get("status", "")).lower()
            is_up = code == 200 and status_value in {"ok", "up", "healthy", ""}
            # Verificar días restantes del certificado SSL
            ssl_expires_days = None
            if scheme == "https":
                try:
                    import ssl as _ssl
                    import socket as _socket
                    from datetime import datetime as _dt
                    ctx = _ssl.create_default_context()
                    with _socket.create_connection((domain, 443), timeout=2) as sock:
                        with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                            cert = ssock.getpeercert()
                            exp_str = cert.get("notAfter", "")
                            if exp_str:
                                exp_dt = _dt.strptime(exp_str, "%b %d %H:%M:%S %Y %Z")
                                ssl_expires_days = (exp_dt - _dt.utcnow()).days
                except Exception:
                    ssl_expires_days = None

            return {
                "state": TenantHealthState.UP if is_up else TenantHealthState.DOWN,
                "domain": domain,
                "url": url,
                "status_code": code,
                "latency_ms": elapsed_ms,
                "checked_at": timezone.now(),
                "schema": payload.get("schema", ""),
                "status_value": payload.get("status", ""),
                "error": "",
                "ssl_expires_days": ssl_expires_days,
            }
        except url_error.HTTPError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            last_error = f"HTTP {exc.code}"
            return {
                "state": TenantHealthState.DOWN,
                "domain": domain,
                "url": url,
                "status_code": exc.code,
                "latency_ms": elapsed_ms,
                "checked_at": timezone.now(),
                "schema": "",
                "status_value": "",
                "error": last_error,
            }
        except Exception as exc:
            last_error = str(exc)
            continue

    return {
        "state": TenantHealthState.DOWN,
        "domain": domain,
        "url": "",
        "status_code": None,
        "latency_ms": None,
        "checked_at": timezone.now(),
        "schema": "",
        "status_value": "",
        "error": last_error or "No fue posible conectar al healthcheck",
    }


def _empty_health_probe(tenant, *, state=TenantHealthState.UNKNOWN, error="Sin chequeos guardados"):
    return {
        "state": state,
        "domain": _tenant_primary_domain(tenant) or "",
        "url": "",
        "status_code": None,
        "latency_ms": None,
        "checked_at": None,
        "schema": "",
        "status_value": "",
        "error": error,
    }


def _probe_from_record(record):
    return {
        "state": record.state,
        "domain": record.domain or "",
        "url": record.url or "",
        "status_code": record.status_code,
        "latency_ms": record.latency_ms,
        "checked_at": record.checked_at,
        "schema": record.schema_name or "",
        "status_value": record.status_value or "",
        "error": record.error or "",
    }


def _delete_tenant_with_schema(tenant):
    try:
        tenant.delete(force_drop=True)
    except TypeError:
        tenant.delete()


def _sync_company_config(schema_name, company_name):
    try:
        with schema_context(schema_name):
            from core.models import CompanyConfig

            config = CompanyConfig.get()
            if config:
                config.legal_name = company_name
                if not config.trade_name:
                    config.trade_name = company_name
                config.save(update_fields=["legal_name", "trade_name"])
    except Exception:
        pass


def _latest_health_checks(tenants):
    tenant_ids = [tenant.pk for tenant in tenants]
    if not tenant_ids:
        return {}
    # django-tenants solo funciona con PostgreSQL; DISTINCT ON evita cargar todo el histórico.
    latest = (
        TenantHealthCheck.objects
        .filter(tenant_id__in=tenant_ids)
        .order_by("tenant_id", "-checked_at", "-id")
        .distinct("tenant_id")
    )
    return {record.tenant_id: record for record in latest}


def _prune_health_checks(*, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = timezone.now() - timedelta(days=retention_days)
    TenantHealthCheck.objects.filter(checked_at__lt=cutoff).delete()


class TenantListView(LoginRequiredMixin, SuperAdminRequiredMixin, ListView):
    model = Client
    template_name = "tenants/tenant_list.html"
    context_object_name = "tenants"
    paginate_by = 50

    def get_queryset(self):
        return Client.objects.prefetch_related("domains", "memberships").order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenants = list(ctx.get("tenants", []))
        ctx["total_tenants"] = len(tenants)
        # Acceso al portal del gateway fiscal (B22) solo desde este panel de
        # super admin. Vacío = no se muestra el botón (p.ej. instalaciones sin B22).
        ctx["b22_portal_url"] = getattr(settings, "B22_PORTAL_URL", "")

        check_health = self.request.GET.get("check_health", "0") == "1"
        ctx["check_health"] = check_health
        health_filter = (self.request.GET.get("health_filter") or "all").strip().lower()
        if health_filter not in {"all", "failed"}:
            health_filter = "all"
        ctx["health_filter"] = health_filter

        if not tenants:
            ctx["tenants"] = tenants
            ctx["failed_tenants_count"] = 0
            ctx["visible_tenants_count"] = 0
            return ctx

        if check_health:
            prefer_https = self.request.is_secure() or bool(getattr(settings, "ENABLE_SSL", False))
            max_workers = min(8, max(1, len(tenants)))
            future_to_tenant = {}
            rows_to_persist = []

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for tenant in tenants:
                    domain = _tenant_primary_domain(tenant)
                    if not domain:
                        probe = _empty_health_probe(
                            tenant,
                            state=TenantHealthState.UNKNOWN,
                            error="Sin dominio configurado",
                        )
                        probe["checked_at"] = timezone.now()
                        tenant.health_probe = probe
                        rows_to_persist.append(
                            TenantHealthCheck(
                                tenant=tenant,
                                domain=probe["domain"],
                                url=probe["url"],
                                state=probe["state"],
                                status_code=probe["status_code"],
                                latency_ms=probe["latency_ms"],
                                schema_name=probe["schema"],
                                status_value=probe["status_value"],
                                error=probe["error"],
                                checked_at=probe["checked_at"] or timezone.now(),
                            )
                        )
                        continue
                    future = pool.submit(_probe_tenant_health, domain, prefer_https=prefer_https)
                    future_to_tenant[future] = tenant

                for future in as_completed(future_to_tenant):
                    tenant = future_to_tenant[future]
                    try:
                        probe = future.result()
                    except Exception as exc:
                        probe = _empty_health_probe(
                            tenant,
                            state=TenantHealthState.DOWN,
                            error=str(exc),
                        )
                        probe["checked_at"] = timezone.now()
                    tenant.health_probe = probe
                    rows_to_persist.append(
                        TenantHealthCheck(
                            tenant=tenant,
                            domain=probe["domain"],
                            url=probe["url"],
                            state=probe["state"],
                            status_code=probe["status_code"],
                            latency_ms=probe["latency_ms"],
                            schema_name=probe["schema"],
                            status_value=probe["status_value"],
                            error=probe["error"],
                            checked_at=probe["checked_at"] or timezone.now(),
                        )
                    )

            if rows_to_persist:
                TenantHealthCheck.objects.bulk_create(rows_to_persist, batch_size=100)
                retention_days = getattr(settings, "TENANT_HEALTH_RETENTION_DAYS", 30)
                try:
                    retention_days = int(retention_days)
                except (TypeError, ValueError):
                    retention_days = 30
                _prune_health_checks(retention_days=retention_days)
        else:
            latest_by_tenant = _latest_health_checks(tenants)
            for tenant in tenants:
                record = latest_by_tenant.get(tenant.pk)
                tenant.health_probe = _probe_from_record(record) if record else _empty_health_probe(tenant)

        failed_tenants = [
            tenant for tenant in tenants
            if getattr(tenant, "health_probe", {}).get("state") in {TenantHealthState.DOWN, TenantHealthState.UNKNOWN}
        ]
        ctx["failed_tenants_count"] = len(failed_tenants)

        if health_filter == "failed":
            tenants = failed_tenants

        ctx["tenants"] = tenants
        ctx["visible_tenants_count"] = len(tenants)
        return ctx


class TenantCreateView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    template_name = "tenants/tenant_form.html"

    def get(self, request):
        form = TenantCreateForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = TenantCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        schema_name = form.cleaned_data["schema_name"]
        name = form.cleaned_data["name"]
        plan = form.cleaned_data.get("plan")
        domain = form.cleaned_data["subdomain"]

        try:
            with transaction.atomic():
                client = Client(
                    schema_name=schema_name,
                    name=name,
                    plan=plan,
                    is_active=True,
                )
                client.auto_create_schema = False
                client.save()
                Domain.objects.create(domain=domain, tenant=client, is_primary=True)
        except IntegrityError as e:
            messages.error(request, f"El schema o dominio ya existe: {str(e)}")
            return render(request, self.template_name, {"form": form})
        except Exception as e:
            messages.error(request, f"Error al crear tenant: {str(e)}")
            return render(request, self.template_name, {"form": form})

        # Crear el schema una sola vez para evitar duplicar migraciones.
        try:
            client.create_schema(check_if_exists=True, verbosity=0)
        except Exception as e:
            messages.error(request, f"Error al migrar schema: {str(e)}")
            _delete_tenant_with_schema(client)
            return render(request, self.template_name, {"form": form})

        try:
            with schema_context(client.schema_name):
                call_command("seed_data", verbosity=0)
        except Exception as e:
            messages.warning(request, f"Tenant creado pero seed_data falló: {str(e)}")

        _sync_company_config(client.schema_name, client.name)

        # Crear o asociar usuario admin al tenant
        username = (form.cleaned_data.get("admin_username") or "").strip()
        email = (form.cleaned_data.get("admin_email") or "").strip()
        password = (form.cleaned_data.get("admin_password") or "").strip()

        if username:
            User = get_user_model()
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "is_staff": True},
            )
            if created or password:
                if email and not user.email:
                    user.email = email
                user.is_staff = True
                user.set_password(password)
                user.save()

            admin_group, _ = Group.objects.get_or_create(name="admin")
            user.groups.add(admin_group)

            TenantMembership.objects.get_or_create(
                tenant=client,
                user=user,
                defaults={"is_admin": True, "is_active": True},
            )

        messages.success(request, f"Empresa '{client.name}' creada correctamente.")
        return redirect("tenants:list")


class TenantEditView(LoginRequiredMixin, SuperAdminRequiredMixin, UpdateView):
    model = Client
    form_class = TenantEditForm
    template_name = "tenants/tenant_edit.html"

    def get_success_url(self):
        messages.success(self.request, f"Empresa '{self.object.name}' actualizada.")
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["domains"] = self.object.domains.all()
        return ctx


class TenantDetailView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains", "memberships__user").first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")
        TenantModule.ensure_all_exist(tenant)
        modules = tenant.modules.order_by("module")
        form = AddMemberForm()
        active_count = tenant.memberships.filter(is_active=True).count()
        max_users = tenant.max_users

        # Cajeros POS (solo si módulo POS activo)
        cashier_assignments = []
        pos_warehouses = []
        tenant_members = []
        if TenantModule.is_enabled(tenant, "pos"):
            from django_tenants.utils import schema_context
            with schema_context(tenant.schema_name):
                from pos.models import POSCashierAssignment
                from core.models import Warehouse, WarehouseType
                cashier_assignments = list(
                    POSCashierAssignment.objects
                    .select_related("user", "warehouse")
                    .order_by("warehouse__name", "user__username")
                )
                pos_warehouses = list(
                    Warehouse.objects.filter(type=WarehouseType.RETAIL, is_active=True).order_by("name")
                )
            from django.contrib.auth import get_user_model
            User = get_user_model()
            member_ids = tenant.memberships.filter(is_active=True).values_list("user_id", flat=True)
            tenant_members = list(User.objects.filter(pk__in=member_ids).order_by("username"))

        # ── Métricas de monitoreo ─────────────────────────────────────────────
        monitoring = {}
        try:
            from django_tenants.utils import schema_context
            from django.contrib.auth import get_user_model
            from django.db.models import Max, Count
            from django.utils import timezone as tz

            _User = get_user_model()

            with schema_context(tenant.schema_name):
                # Último login por usuario del tenant
                member_ids = list(tenant.memberships.values_list("user_id", flat=True))
                last_logins = list(
                    _User.objects.filter(pk__in=member_ids)
                    .exclude(last_login__isnull=True)
                    .values("username", "last_login")
                    .order_by("-last_login")[:5]
                )
                last_login = last_logins[0]["last_login"] if last_logins else None

                # Facturas emitidas este mes
                try:
                    from sales.models import SaleInvoice, InvoiceStatus
                    month_start = tz.now().replace(day=1, hour=0, minute=0, second=0)
                    invoice_count_month = SaleInvoice.objects.filter(
                        created_at__gte=month_start
                    ).count()
                    invoice_count_total = SaleInvoice.objects.count()
                    invoice_authorized = SaleInvoice.objects.filter(
                        status=InvoiceStatus.AUTHORIZED
                    ).count()
                except Exception:
                    invoice_count_month = invoice_count_total = invoice_authorized = 0

                # Eventos contables pendientes
                try:
                    from finance.models import AccountingEvent, AccountingEventStatus
                    pending_events = AccountingEvent.objects.filter(
                        status=AccountingEventStatus.NEW
                    ).count()
                    error_events = AccountingEvent.objects.filter(
                        status=AccountingEventStatus.ERROR
                    ).count()
                except Exception:
                    pending_events = error_events = 0

                # NCs abiertas
                try:
                    from capa.models import NonConformity, NonConformityStatus
                    open_ncs = NonConformity.objects.exclude(
                        status=NonConformityStatus.CLOSED
                    ).count()
                    critical_ncs = NonConformity.objects.filter(
                        severity="CRITICAL"
                    ).exclude(status=NonConformityStatus.CLOSED).count()
                except Exception:
                    open_ncs = critical_ncs = 0

                # Productos y stock
                try:
                    from inventory.models import Product, Stock
                    product_count = Product.objects.filter(is_active=True).count()
                    stock_total = Stock.objects.count()
                except Exception:
                    product_count = stock_total = 0

                # Órdenes de producción activas
                try:
                    from production.models import ProductionOrder, ProductionOrderStatus
                    active_ops = ProductionOrder.objects.filter(
                        status__in=[
                            ProductionOrderStatus.RELEASED,
                            ProductionOrderStatus.IN_PROGRESS,
                        ]
                    ).count()
                except Exception:
                    active_ops = 0

            # ── Storage: tamaño de carpeta media del tenant ──────────────
            storage_mb = None
            try:
                import os
                from django.conf import settings as dj_settings
                media_path = os.path.join(dj_settings.MEDIA_ROOT, tenant.schema_name)
                if os.path.exists(media_path):
                    total_bytes = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, _, files in os.walk(media_path)
                        for f in files
                    )
                    storage_mb = round(total_bytes / (1024 * 1024), 2)
                else:
                    storage_mb = 0.0
            except Exception:
                storage_mb = None

            # ── Storage: tamaño del schema en PostgreSQL ──────────────────
            db_mb = None
            try:
                from django.db import connection as _conn
                with _conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) "
                        "FROM pg_tables WHERE schemaname = %s LIMIT 1",
                        [tenant.schema_name]
                    )
                    # Calcular total del schema
                    cur.execute(
                        "SELECT ROUND(SUM(pg_total_relation_size(schemaname || '.' || tablename)) / 1048576.0, 2) "
                        "FROM pg_tables WHERE schemaname = %s",
                        [tenant.schema_name]
                    )
                    row = cur.fetchone()
                    db_mb = float(row[0]) if row and row[0] else 0.0
            except Exception:
                db_mb = None

            # ── Último backup ─────────────────────────────────────────────
            last_backup = None
            try:
                import glob
                backup_pattern = f"/tmp/backup_*{tenant.schema_name}*.sql"
                backups = glob.glob(backup_pattern)
                if not backups:
                    backup_pattern2 = "/tmp/backup_pre_deploy_*.sql"
                    backups = glob.glob(backup_pattern2)
                if backups:
                    latest = max(backups, key=os.path.getmtime)
                    last_backup = timezone.datetime.fromtimestamp(os.path.getmtime(latest))
            except Exception:
                last_backup = None

            # ── Versión de migraciones ────────────────────────────────────
            migrations_ok = None
            pending_migrations = 0
            try:
                from django.db.migrations.executor import MigrationExecutor
                from django.db import connections
                # Cambiar al schema del tenant
                with schema_context(tenant.schema_name):
                    executor = MigrationExecutor(connections['default'])
                    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
                    pending_migrations = len(plan)
                    migrations_ok = pending_migrations == 0
            except Exception:
                migrations_ok = None

            monitoring = {
                "last_login": last_login,
                "last_logins": last_logins,
                "invoice_count_month": invoice_count_month,
                "invoice_count_total": invoice_count_total,
                "invoice_authorized": invoice_authorized,
                "pending_events": pending_events,
                "error_events": error_events,
                "open_ncs": open_ncs,
                "critical_ncs": critical_ncs,
                "product_count": product_count,
                "active_ops": active_ops,
                # Nuevos
                "storage_mb": storage_mb,
                "db_mb": db_mb,
                "last_backup": last_backup,
                "migrations_ok": migrations_ok,
                "pending_migrations": pending_migrations,
            }
        except Exception:
            monitoring = {}

        # Perfil regulatorio ACTUAL: no se guarda como campo, se deriva de los
        # módulos habilitados. Es la edición cuyos módulos están TODOS activos;
        # si varias califican, gana la más específica (más módulos).
        _enabled = TenantModule.get_enabled_set(tenant)
        current_edition = None
        _best = -1
        for _key, _data in TENANT_EDITIONS.items():
            _ed = set(_data["modules"])
            if _ed and _ed <= _enabled and len(_ed) > _best:
                current_edition = _key
                _best = len(_ed)

        return render(request, "tenants/tenant_detail.html", {
            "tenant": tenant,
            "form": form,
            "tenant_modules": modules,
            "active_member_count": active_count,
            "max_users": max_users,
            "cashier_assignments": cashier_assignments,
            "pos_warehouses": pos_warehouses,
            "tenant_members": tenant_members,
            "tenant_editions": TENANT_EDITIONS,
            "current_edition": current_edition,
            "current_edition_label": TENANT_EDITIONS[current_edition]["label"] if current_edition else None,
            "monitoring": monitoring,
        })

    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains", "memberships__user").first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")

        form = AddMemberForm(request.POST)
        if form.is_valid():
            try:
                result = save_tenant_user_account(
                    tenant,
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data.get("password", ""),
                    is_admin=form.cleaned_data["is_admin"],
                    allow_create=False,
                    allow_global_user_updates=True,
                )
            except TenantUserAccountError as exc:
                messages.error(request, str(exc))
                return redirect("tenants:detail", pk=tenant.pk)

            user = result.user
            if result.membership_created:
                messages.success(request, f"Usuario '{user.username}' agregado.")
            elif result.membership_reactivated:
                messages.success(request, f"Usuario '{user.username}' reactivado.")
            elif result.password_updated:
                messages.success(request, f"Contraseña de '{user.username}' actualizada.")
            elif result.membership_admin_updated:
                messages.success(request, f"Permisos de '{user.username}' actualizados.")
            else:
                messages.info(request, f"'{user.username}' ya es miembro de esta empresa.")
            return redirect("tenants:detail", pk=tenant.pk)

        messages.error(request, "Revisa los datos del usuario.")
        return redirect("tenants:detail", pk=tenant.pk)


class TenantModuleToggleView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk, module):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")

        valid_modules = {m[0] for m in AVAILABLE_MODULES}
        if module not in valid_modules:
            messages.error(request, "Módulo no válido.")
            return redirect("tenants:detail", pk=pk)

        flag, _ = TenantModule.objects.get_or_create(
            tenant=tenant, module=module,
            defaults={"enabled": False},
        )
        flag.enabled = not flag.enabled
        flag.save(update_fields=["enabled", "updated_at"])

        label = dict(AVAILABLE_MODULES).get(module, module)
        estado = "habilitado" if flag.enabled else "deshabilitado"
        messages.success(request, f"Módulo '{label}' {estado} para {tenant.name}.")
        return redirect("tenants:detail", pk=pk)


class TenantApplyEditionView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    """Aplica un perfil de edicion al tenant activando el conjunto de modulos correspondiente."""
    def post(self, request, pk, edition):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")

        if edition not in TENANT_EDITIONS:
            messages.error(request, f"Edicion '{edition}' no existe.")
            return redirect("tenants:detail", pk=pk)

        edition_data = TENANT_EDITIONS[edition]
        modules_to_enable = set(edition_data["modules"])
        all_module_ids = {m[0] for m in AVAILABLE_MODULES}

        # Asegurar que existen registros para todos los modulos
        TenantModule.ensure_all_exist(tenant)

        # Activar los del perfil, desactivar el resto
        updated = 0
        for module_id in all_module_ids:
            should_be_enabled = module_id in modules_to_enable
            changed = TenantModule.objects.filter(tenant=tenant, module=module_id).update(
                enabled=should_be_enabled
            )
            updated += changed

        messages.success(
            request,
            f"Perfil '{edition_data['label']}' aplicado a {tenant.name}. "
            f"Modulos activos: {', '.join(sorted(modules_to_enable))}."
        )
        return redirect("tenants:detail", pk=pk)


class TenantCashierAssignView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    """Asigna un usuario como cajero de un punto de venta del tenant."""
    def post(self, request, pk):
        from django_tenants.utils import schema_context
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            return redirect("tenants:list")

        user_id = request.POST.get("user_id")
        warehouse_id = request.POST.get("warehouse_id")

        if not user_id or not warehouse_id:
            messages.error(request, "Selecciona usuario y punto de venta.")
            return redirect("tenants:detail", pk=pk)

        with schema_context(tenant.schema_name):
            from django.contrib.auth import get_user_model
            from pos.models import POSCashierAssignment
            from core.models import Warehouse
            User = get_user_model()
            user = User.objects.filter(pk=user_id).first()
            warehouse = Warehouse.objects.filter(pk=warehouse_id, type__exact="RETAIL").first()
            if not user or not warehouse:
                messages.error(request, "Usuario o punto de venta no válido.")
                return redirect("tenants:detail", pk=pk)
            assignment, created = POSCashierAssignment.objects.get_or_create(
                user=user, warehouse=warehouse,
                defaults={"is_active": True}
            )
            if not created:
                assignment.is_active = True
                assignment.save(update_fields=["is_active"])
            messages.success(request, f"{user.get_full_name() or user.username} asignado a {warehouse.name}.")
        return redirect("tenants:detail", pk=pk)


class TenantCashierAssignToggleView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    """Activa/desactiva una asignación de cajero."""
    def post(self, request, pk, assignment_pk):
        from django_tenants.utils import schema_context
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            return redirect("tenants:list")
        with schema_context(tenant.schema_name):
            from pos.models import POSCashierAssignment
            assignment = POSCashierAssignment.objects.filter(pk=assignment_pk).first()
            if assignment:
                assignment.is_active = not assignment.is_active
                assignment.save(update_fields=["is_active"])
        return redirect("tenants:detail", pk=pk)


class TenantToggleActiveView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=["is_active"])
        estado = "activada" if tenant.is_active else "desactivada"
        messages.success(request, f"Empresa '{tenant.name}' {estado}.")
        return redirect("tenants:detail", pk=tenant.pk)


class MembershipToggleView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active"])
        estado = "activado" if membership.is_active else "desactivado"
        messages.success(request, f"Usuario '{membership.user.username}' {estado}.")
        return redirect("tenants:detail", pk=membership.tenant.pk)


class MembershipDeleteView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        tenant_pk = membership.tenant.pk
        username = membership.user.username
        membership.delete()
        messages.success(request, f"Usuario '{username}' removido de la empresa.")
        return redirect("tenants:detail", pk=tenant_pk)


class TenantSwitchView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains").first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")

        domain = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
        if not domain:
            messages.error(request, "La empresa no tiene dominio configurado.")
            return redirect("tenants:list")

        host = request.get_host()  # ej: localhost:8000
        port = ""
        if ":" in host:
            port = ":" + host.split(":")[-1]
        target = f"{request.scheme}://{domain.domain}{port}/"
        return redirect(target)


# ──────────────────────────────────────────────
#  Plan CRUD (solo superadmin, schema público)
# ──────────────────────────────────────────────

class PlanListView(LoginRequiredMixin, SuperAdminRequiredMixin, ListView):
    model = Plan
    template_name = "tenants/plan_list.html"
    context_object_name = "plans"

    def get_queryset(self):
        return Plan.objects.annotate(
            client_count=models.Count('clients')
        ).order_by('max_users')


class PlanCreateView(LoginRequiredMixin, SuperAdminRequiredMixin, CreateView):
    model = Plan
    form_class = PlanForm
    template_name = "tenants/plan_form.html"

    def get_success_url(self):
        messages.success(self.request, f"Plan '{self.object.name}' creado.")
        return reverse("tenants:plan_list")


class PlanEditView(LoginRequiredMixin, SuperAdminRequiredMixin, UpdateView):
    model = Plan
    form_class = PlanForm
    template_name = "tenants/plan_form.html"

    def get_success_url(self):
        messages.success(self.request, f"Plan '{self.object.name}' actualizado.")
        return reverse("tenants:plan_list")


class PlanToggleView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        plan = Plan.objects.filter(pk=pk).first()
        if not plan:
            messages.error(request, "Plan no encontrado.")
            return redirect("tenants:plan_list")
        plan.is_active = not plan.is_active
        plan.save(update_fields=["is_active"])
        estado = "activado" if plan.is_active else "desactivado"
        messages.success(request, f"Plan '{plan.name}' {estado}.")
        return redirect("tenants:plan_list")
