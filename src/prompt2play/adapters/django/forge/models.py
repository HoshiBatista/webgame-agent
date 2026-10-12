import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def empty_usage():
    return {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "calls": 0,
    }


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=180, blank=True, default="")
    prompt = models.TextField(max_length=12000)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    latest_version = models.ForeignKey(
        "Version", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        return self.title


class Runner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)
    capabilities = models.JSONField(default=dict)
    role = models.CharField(
        max_length=12,
        choices=[("generator", "generator"), ("validator", "validator")],
        default="generator",
    )

    @property
    def is_authenticated(self):
        return True

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Version(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    prompt = models.TextField(max_length=12000)
    summary = models.TextField(blank=True, max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_reference = models.BooleanField(default=False)
    validation = models.JSONField(default=dict)
    usage = models.JSONField(default=empty_usage)
    spec = models.JSONField(default=dict)
    files = models.JSONField(default=dict)
    html = models.TextField()
    candidate = models.OneToOneField(
        "Candidate", null=True, blank=True, on_delete=models.PROTECT, related_name="version"
    )
    eligible = models.BooleanField(default=False)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="unique_project_version"),
            models.CheckConstraint(condition=Q(number__gte=1), name="positive_version_number"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Опубликованные версии неизменяемы. Создайте новую версию.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project_id} / v{self.number}"


class Job(models.Model):
    STATUS = [
        (s, s)
        for s in ["queued", "running", "waiting", "paused", "completed", "failed", "cancelled"]
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="jobs")
    kind = models.CharField(max_length=12, choices=[("generate", "generate"), ("revise", "revise")])
    prompt = models.TextField(max_length=12000)
    provider = models.CharField(max_length=12, choices=[("codex", "codex"), ("openai", "openai")])
    model = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="queued", db_index=True)
    stage = models.CharField(max_length=32, default="plan")
    progress = models.FloatField(default=0)
    base_version = models.ForeignKey(
        Version, null=True, blank=True, on_delete=models.PROTECT, related_name="revision_jobs"
    )
    result_version = models.ForeignKey(
        Version, null=True, blank=True, on_delete=models.PROTECT, related_name="result_jobs"
    )
    runner = models.ForeignKey(
        Runner, null=True, blank=True, on_delete=models.PROTECT, related_name="jobs"
    )
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error = models.TextField(blank=True, max_length=4000)
    max_repairs = models.PositiveSmallIntegerField(default=2)
    playthrough_mode = models.CharField(
        max_length=10, choices=[("manual", "manual"), ("auto", "auto")], default="manual"
    )
    budget_tokens = models.PositiveIntegerField(default=400000)
    budget_usd = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    pricing = models.JSONField(default=dict)
    cost_nano = models.PositiveBigIntegerField(default=0)
    cost_upper_nano = models.PositiveBigIntegerField(default=0)
    budget_seconds = models.PositiveIntegerField(null=True, blank=True, default=None)
    resume_count = models.PositiveSmallIntegerField(default=0)
    execution_expires_at = models.DateTimeField(null=True, blank=True)
    usage = models.JSONField(default=empty_usage)
    creation_mode = models.CharField(
        max_length=4, choices=[("lite", "lite"), ("pro", "pro")], default="lite"
    )
    pause_requested = models.BooleanField(default=False)
    review = models.JSONField(default=dict)
    checkpoint = models.JSONField(default=dict)
    lease_hash = models.CharField(max_length=64, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stage_fence = models.PositiveBigIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    active_candidate = models.ForeignKey(
        "Candidate", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=Q(status__in=["queued", "running", "waiting", "paused"]),
                name="one_active_job_per_project",
            )
        ]


class Event(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="events")
    stage = models.CharField(max_length=32)
    level = models.CharField(
        max_length=10, choices=[("info", "info"), ("warning", "warning"), ("error", "error")]
    )
    message = models.TextField(max_length=2000)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class Candidate(models.Model):
    """Immutable bytes committed before validation, including failed attempts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="candidates")
    generator = models.ForeignKey(Runner, on_delete=models.PROTECT, related_name="candidates")
    parent = models.ForeignKey(
        Version, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    attempt = models.PositiveIntegerField()
    submission_key = models.CharField(max_length=160)
    stage_fence = models.PositiveBigIntegerField()
    artifact_key = models.CharField(max_length=64)
    intent = models.CharField(max_length=32)
    committed = models.BooleanField(default=False)
    artifact = models.JSONField(default=dict)
    summary = models.TextField(max_length=3000, blank=True)
    usage = models.JSONField(default=empty_usage)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["attempt"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "submission_key"], name="unique_candidate_submission"
            ),
            models.UniqueConstraint(fields=["job", "attempt"], name="unique_job_attempt"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Кандидаты неизменяемы.")
        return super().save(*args, **kwargs)


class ValidationResult(models.Model):
    candidate = models.OneToOneField(
        Candidate, primary_key=True, on_delete=models.PROTECT, related_name="result"
    )
    validator = models.ForeignKey(Runner, on_delete=models.PROTECT)
    report = models.JSONField()
    outcome = models.CharField(max_length=12)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Результаты проверки неизменяемы.")
        return super().save(*args, **kwargs)


class ModelInvocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="invocations")
    generator = models.ForeignKey(
        Runner, null=True, on_delete=models.PROTECT, related_name="invocations"
    )
    actual_usage = models.JSONField(null=True, blank=True)
    invocation_key = models.CharField(max_length=160)
    operation = models.CharField(max_length=64)
    prompt_sha256 = models.CharField(max_length=64)
    stage_fence = models.PositiveBigIntegerField()
    reserved_tokens = models.PositiveIntegerField()
    reserved_cost_nano = models.PositiveBigIntegerField(default=0)
    cost_nano = models.PositiveBigIntegerField(null=True, blank=True)
    cost_upper_nano = models.PositiveBigIntegerField(null=True, blank=True)
    state = models.CharField(max_length=12, default="reserved")
    response_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "invocation_key"], name="unique_model_invocation"
            )
        ]
