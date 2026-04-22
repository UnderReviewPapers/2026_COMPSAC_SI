from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('ProductionLeader', 'Production Leader'),
        ('ForgingProcessSupplier', 'Forging Process Supplier'),
        ('MechanicalPartSupplier', 'Mechanical Part Supplier'),
    ]
    role = models.CharField(max_length=50, choices=ROLE_CHOICES)