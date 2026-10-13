from shop.validators import validate_assigned_mechanic, validate_single_assignment


class AssignedToShopMixin:
    """Shared validation for models that assign work to a mechanic user OR a shop."""

    def clean(self) -> None:
        super().clean()
        assigned_to = getattr(self, "assigned_to", None)
        assigned_shop = getattr(self, "assigned_shop", None)
        validate_single_assignment(assigned_to, assigned_shop)
        validate_assigned_mechanic(assigned_to)

    def save(self, *args: object, **kwargs: object):
        self.clean()
        return super().save(*args, **kwargs)
