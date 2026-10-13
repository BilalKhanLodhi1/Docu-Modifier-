"""Delete stored files when their database rows are deleted."""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Document, DocumentVersion, JobOutput


def _delete_file(field):
    if field and field.name:
        storage = field.storage
        if storage.exists(field.name):
            storage.delete(field.name)


@receiver(post_delete, sender=Document)
def _doc_deleted(sender, instance, **kwargs):
    _delete_file(instance.original_file)


@receiver(post_delete, sender=DocumentVersion)
def _version_deleted(sender, instance, **kwargs):
    # Version 1 shares the original upload's file; Document deletion handles it.
    if instance.operation != "upload":
        _delete_file(instance.file)


@receiver(post_delete, sender=JobOutput)
def _output_deleted(sender, instance, **kwargs):
    _delete_file(instance.file)
