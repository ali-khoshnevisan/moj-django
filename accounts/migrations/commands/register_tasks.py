from django.core.management.base import BaseCommand
from background_task.models import Task

# from ai.tasks import ai_process
from crawler.tasks import crawler_process
from social_media.tasks import action_process, profile_process

TASK_SCHEDULE = 0
tasks = [
    # {
    #     "task": ai_process,
    #     "repeat": 60
    # },
    {
        "task": crawler_process,
        "repeat": 60
    },
    {
        "task": action_process,
        "repeat": 60
    },
    {
        "task": profile_process,
        "repeat": 60
    },
]


class Command(BaseCommand):
    help = "Register and sync background tasks"

    def handle(self, *args, **options):
        Task.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Old tasks are deleted."))

        for t in tasks:
            func = t["task"]
            name = f"{func.__module__}.{func.__name__}"
            func(schedule=TASK_SCHEDULE, repeat=t["repeat"])
            self.stdout.write(self.style.SUCCESS(f"Created: {name}"))

        self.stdout.write(self.style.SUCCESS("Sync complete."))
