from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator

from app.cuentas.decorators import nivel_requerido
from .models import Empresa, Area, Plano, Unidad, Material, Configuracion
from .forms import (
    EmpresaForm, AreaForm, PlanoForm,
    UnidadForm, MaterialForm, ConfiguracionForm,
)


# ─── Helper genérico ──────────────────────────────────────────────────────────

def _crud_list(request, Model, Form, template, nombre_entidad, url_list):
    """Vista genérica list + create para los catálogos simples."""
    qs = Model.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(nombre__icontains=q)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    form = Form(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{nombre_entidad} guardado correctamente.")
        return redirect(url_list)

    return render(request, template, {
        "page_obj": page_obj,
        "form": form,
        "q": q,
        "nombre_entidad": nombre_entidad,
    })


def _crud_toggle(request, Model, pk, url_list):
    """Activa / desactiva (toggle) el campo `activa` o `activo`."""
    obj = get_object_or_404(Model, pk=pk)
    campo = "activa" if hasattr(obj, "activa") else "activo"
    setattr(obj, campo, not getattr(obj, campo))
    obj.save(update_fields=[campo])
    return redirect(url_list)


def _crud_edit(request, Model, Form, pk, template, nombre_entidad, url_list):
    """Vista de edición genérica."""
    obj = get_object_or_404(Model, pk=pk)
    form = Form(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{nombre_entidad} actualizado.")
        return redirect(url_list)
    return render(request, template, {"form": form, "obj": obj, "nombre_entidad": nombre_entidad})


# ─── Empresas ─────────────────────────────────────────────────────────────────

@nivel_requerido(6)
def empresas(request):
    return _crud_list(request, Empresa, EmpresaForm,
                      "almacen/ti/catalogos/empresas.html", "Empresa", "catalogos:empresas")


@nivel_requerido(6)
def empresa_editar(request, pk):
    return _crud_edit(request, Empresa, EmpresaForm, pk,
                      "almacen/ti/catalogos/catalogo_edit.html", "Empresa", "catalogos:empresas")


@nivel_requerido(6)
def empresa_toggle(request, pk):
    return _crud_toggle(request, Empresa, pk, "catalogos:empresas")


# ─── Áreas ────────────────────────────────────────────────────────────────────

@nivel_requerido(6)
def areas(request):
    return _crud_list(request, Area, AreaForm,
                      "almacen/ti/catalogos/areas.html", "Área", "catalogos:areas")


@nivel_requerido(6)
def area_editar(request, pk):
    return _crud_edit(request, Area, AreaForm, pk,
                      "almacen/ti/catalogos/catalogo_edit.html", "Área", "catalogos:areas")


@nivel_requerido(6)
def area_toggle(request, pk):
    return _crud_toggle(request, Area, pk, "catalogos:areas")


# ─── Planos ───────────────────────────────────────────────────────────────────

@nivel_requerido(6)
def planos(request):
    return _crud_list(request, Plano, PlanoForm,
                      "almacen/ti/catalogos/planos.html", "Plano", "catalogos:planos")


@nivel_requerido(6)
def plano_editar(request, pk):
    return _crud_edit(request, Plano, PlanoForm, pk,
                      "almacen/ti/catalogos/catalogo_edit.html", "Plano", "catalogos:planos")


@nivel_requerido(6)
def plano_toggle(request, pk):
    return _crud_toggle(request, Plano, pk, "catalogos:planos")


# ─── Unidades ─────────────────────────────────────────────────────────────────

@nivel_requerido(6)
def unidades(request):
    return _crud_list(request, Unidad, UnidadForm,
                      "almacen/ti/catalogos/unidades.html", "Unidad", "catalogos:unidades")


@nivel_requerido(6)
def unidad_editar(request, pk):
    return _crud_edit(request, Unidad, UnidadForm, pk,
                      "almacen/ti/catalogos/catalogo_edit.html", "Unidad", "catalogos:unidades")


@nivel_requerido(6)
def unidad_toggle(request, pk):
    return _crud_toggle(request, Unidad, pk, "catalogos:unidades")


# ─── Materiales ───────────────────────────────────────────────────────────────

@nivel_requerido(6)
def materiales(request):
    qs = Material.objects.select_related("unidad_sugerida").all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(descripcion__icontains=q)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    form = MaterialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Material guardado correctamente.")
        return redirect("catalogos:materiales")
    return render(request, "almacen/ti/catalogos/materiales.html", {
        "page_obj": page_obj, "form": form, "q": q,
    })


@nivel_requerido(6)
def material_editar(request, pk):
    return _crud_edit(request, Material, MaterialForm, pk,
                      "almacen/ti/catalogos/catalogo_edit.html", "Material", "catalogos:materiales")


@nivel_requerido(6)
def material_toggle(request, pk):
    return _crud_toggle(request, Material, pk, "catalogos:materiales")


# ─── Buscador de materiales (vale de Nivel 1 / despacho) ─────────────────────

from django.db.models import Q
from app.cuentas.decorators import login_perfil_requerido


@login_perfil_requerido
@nivel_requerido(1)
def material_buscar(request):
    """JSON: ?q=PUER → [{id, folio, descripcion, unidad, unidad_id}]. Máx. 20.
    FULLTEXT primero (q≥4), folio siempre por folio, fallback LIKE ante todo."""
    import logging as _logging
    from django.http import JsonResponse as JR
    from django.db.models.expressions import RawSQL
    q = request.GET.get("q", "").strip()
    out = []
    if len(q) >= 2:
        mats = []
        if len(q) >= 4:
            try:
                _match = "MATCH(descripcion) AGAINST (%s IN NATURAL LANGUAGE MODE)"
                _ft_ids = list(
                    Material.objects.filter(activa=True)
                    .annotate(_rel=RawSQL(_match, (q,)))
                    .filter(_rel__gt=0)
                    .order_by("-_rel")
                    .values_list("id", flat=True)[:20]
                )
                _folio_ids = list(
                    Material.objects.filter(activa=True, folio__icontains=q)
                    .exclude(pk__in=_ft_ids)
                    .values_list("id", flat=True)[:20]
                )
                _ids = (_ft_ids + _folio_ids)[:20]
                if _ids:
                    _map = {m.pk: m for m in
                            Material.objects.filter(pk__in=_ids).select_related("unidad_sugerida")}
                    mats = [_map[i] for i in _ids if i in _map]
            except Exception as exc:
                _logging.getLogger(__name__).warning("FULLTEXT fallback LIKE: %s", exc)
                mats = []
        if not mats:
            mats = list(
                Material.objects.filter(activa=True)
                .filter(Q(folio__icontains=q) | Q(descripcion__icontains=q))
                .select_related("unidad_sugerida").order_by("folio")[:20])
        for m in mats:
            out.append({
                "id": m.pk,
                "folio": m.folio,
                "descripcion": m.descripcion,
                "unidad": (m.unidad_sugerida.abreviatura or m.unidad_sugerida.nombre)
                          if m.unidad_sugerida else "",
                "unidad_id": m.unidad_sugerida_id,
            })
    return JR({"resultados": out})


# ─── Configuración global (singleton) ────────────────────────────────────────

@nivel_requerido(6)
def configuracion(request):
    cfg = Configuracion.get_solo()
    form = ConfiguracionForm(request.POST or None, request.FILES or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Configuración actualizada correctamente.")
        return redirect("catalogos:configuracion")
    return render(request, "almacen/ti/configuracion.html", {"form": form, "cfg": cfg})
