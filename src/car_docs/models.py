from django.db import models

from shop.models.car import Car


class CarDoc(models.Model):
    """Documentation or notes linked to a specific car."""

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='docs')
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    file = models.FileField(upload_to='car_docs/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self) -> str:
        return f"{self.title} ({self.car})"
