# ds-designer/management/commands/create_test_users.py

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create initial test users for the system'

    def handle(self, *args, **kwargs):
        User = get_user_model()

        users_data = [
            {'username': 'maria', 'password': 'test123', 'role': 'ProductionLeader'},
            {'username': 'paolo', 'password': 'test123', 'role': 'ForgingProcessSupplier'},
            {'username': 'mario', 'password': 'test123', 'role': 'MechanicalPartSupplier'},
        ]

        for user_data in users_data:
            if not User.objects.filter(username=user_data['username']).exists():
                User.objects.create_user(
                    username=user_data['username'],
                    password=user_data['password'],
                    role=user_data['role']
                )
                self.stdout.write(self.style.SUCCESS(
                    f"Created user {user_data['username']} with role {user_data['role']}"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"User {user_data['username']} already exists"
                ))