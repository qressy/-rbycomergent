import os
import sys

from celery import Celery
from celery.signals import setup_logging
from celery.signals import task_prerun, task_postrun, task_failure, worker_ready

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

print(f"[DIAG celery_app] loading chattersift Celery app pid={os.getpid()} settings={os.environ.get('DJANGO_SETTINGS_MODULE')}", flush=True)

app = Celery("chattersift")


@worker_ready.connect
def _worker_ready(**_kwargs):
    print(f"[DIAG celery] worker READY pid={os.getpid()}", flush=True)
    sys.stdout.flush()


@task_prerun.connect
def _task_prerun(task_id=None, task=None, **_kwargs):
    print(f"[DIAG celery] task_prerun pid={os.getpid()} task={task.name if task else '?'} id={task_id}", flush=True)
    sys.stdout.flush()


@task_postrun.connect
def _task_postrun(task_id=None, task=None, state=None, **_kwargs):
    print(f"[DIAG celery] task_postrun pid={os.getpid()} task={task.name if task else '?'} id={task_id} state={state}", flush=True)
    sys.stdout.flush()


@task_failure.connect
def _task_failure(task_id=None, exception=None, sender=None, traceback=None, einfo=None, **_kwargs):
    name = getattr(sender, "name", "?")
    print(f"[DIAG celery] task_FAILURE pid={os.getpid()} task={name} id={task_id} exc={exception.__class__.__name__}: {exception}", flush=True)
    if einfo:
        print(f"[DIAG celery] traceback:\n{einfo.traceback}", flush=True)
    sys.stdout.flush()

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")


@setup_logging.connect
def config_loggers(*args, **kwargs):
    from logging.config import dictConfig  # noqa: PLC0415

    from django.conf import settings  # noqa: PLC0415

    dictConfig(settings.LOGGING)


# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
