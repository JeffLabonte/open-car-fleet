from django.db import models
from .car import Car


class Report(models.Model):
    """A historical report for work done on a car.

    - `job_name`: the name/title of the work performed
    - `date_done`: date when the work was completed
    - `documents`: list of URLs or paths to documents (stored as JSON)
    - `photos`: list of URLs or paths to photos (stored as JSON)
    - `note`: freeform note about the work
    """

    car = models.ForeignKey(Car, related_name="reports", on_delete=models.CASCADE)
    mileage = models.PositiveIntegerField(null=True, blank=True) 
    job_name = models.CharField(max_length=200)
    date_done = models.DateField()
    documents = models.JSONField(default=list, blank=True)
    photos = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.job_name} on {self.date_done} for {self.car}"
