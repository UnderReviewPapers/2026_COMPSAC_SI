from django.db import models

#--------------NON USATO ORM DJANGO -> TUTTO IN MONGO-------------#
class BPMNDiagram(models.Model):
    name = models.CharField(max_length=255)
    xml_content = models.TextField()  # BPMN XML
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class AtomicService(models.Model):
    diagram = models.ForeignKey(BPMNDiagram, on_delete=models.CASCADE, related_name='atomic_services')
    task_id = models.CharField(max_length=255)  # ID BPMN tipo "Activity_1234"
    name = models.CharField(max_length=255)
    
    atomic_type = models.CharField(
        max_length=50,
        choices=[
            ('collect', 'Collect'),
            ('dispatch', 'Dispatch'),
            ('process&monitor', 'Process & Monitor'),
            ('display', 'Display')
        ]
    )
    
    input_params = models.JSONField(default=list)
    output_params = models.JSONField(default=list)

    method = models.CharField(
    max_length=10,
    choices=[
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('DELETE', 'DELETE')
    ],
    default='GET'  # <-- valore di default
)

    url = models.URLField()

    def __str__(self):
        return f"{self.name} ({self.atomic_type})"
