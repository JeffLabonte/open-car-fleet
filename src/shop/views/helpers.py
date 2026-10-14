from typing import Any, Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from shop.importers import CSVImporter, ImportContext, ImportResult, ImportValidationError

ModelSaver = Callable[[Any, Any], None]
PostSaver = Callable[[Any, Any], None]
SuccessUrlResolver = Callable[[Any], str]
ModelResolver = Callable[[], str]
ImportMessageResolver = Callable[[ImportResult], str]


def handle_model_form(
    request: HttpRequest,
    form_class: type,
    template_name: str,
    success_url: str | SuccessUrlResolver,
    *,
    instance: Any = None,
    form_kwargs: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    save_callback: ModelSaver | None = None,
    post_save_callback: PostSaver | None = None,
    success_message: str | None = None,
) -> HttpResponse:
    """Render and process a model form for create/update views.

    ``save_callback`` receives ``(instance, form)`` after ``form.save(commit=False)``
    and is expected to set any foreign keys before the instance is saved.

    ``post_save_callback`` receives ``(instance, form)`` after the instance has
    been saved and can be used for side effects such as creating related objects.

    ``success_url`` may be a URL string or a callable that receives the saved
    instance and returns a URL.
    """
    form_kwargs = dict(form_kwargs or {})
    if instance is not None:
        form_kwargs["instance"] = instance
    is_create = instance is None

    if request.method == "POST":
        form = form_class(request.POST, request.FILES, **form_kwargs)
        if form.is_valid():
            obj = form.save(commit=False)
            if save_callback is not None:
                save_callback(obj, form)
            obj.save()
            if post_save_callback is not None:
                post_save_callback(obj, form)
            messages.success(
                request,
                success_message or (_("Created successfully.") if is_create else _("Updated successfully.")),
            )
            resolved_url = success_url(obj) if callable(success_url) else success_url
            return redirect(resolved_url)
    else:
        form = form_class(**form_kwargs)

    ctx: dict[str, Any] = {"form": form, "is_create": is_create}
    if context:
        ctx.update(context)
    return render(request, template_name, ctx)


def process_import_form(
    request: HttpRequest,
    form,
    model_resolver: ModelResolver,
    context: ImportContext,
    *,
    success_url: str,
    success_message: ImportMessageResolver,
    dry_run_message: ImportMessageResolver,
) -> HttpResponse | None:
    """Run a CSV import from a valid bound import form and surface messages.

    Returns a redirect response on a successful non-dry-run import, otherwise
    ``None``. The caller should re-render the form in the ``None`` case.
    """
    importer = CSVImporter()
    uploaded_file = form.cleaned_data["import_file"]
    dry_run = form.cleaned_data["dry_run"]
    try:
        records = importer.parse_csv_bytes(uploaded_file.read(), source_name=uploaded_file.name)
        result = importer.import_records(
            importer.resolve_model(model_resolver()),
            records,
            context=context,
            dry_run=dry_run,
        )
    except ImportValidationError as exc:
        form.add_error("import_file", str(exc))
        return None

    for warning in result.warnings:
        messages.warning(
            request,
            _("Record %(number)s: %(message)s") % {"number": warning.record_number, "message": warning.message},
        )

    if result.has_errors:
        for error in result.errors:
            messages.error(
                request,
                _("Record %(number)s: %(message)s") % {"number": error.record_number, "message": error.message},
            )
        form.add_error("import_file", _("Import validation failed. Fix the file and try again."))
        return None

    if dry_run:
        messages.success(request, dry_run_message(result))
        return None

    messages.success(request, success_message(result))
    return redirect(success_url)
