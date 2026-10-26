import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .titles import DEFAULT_CHAT_TITLE


class User(AbstractUser):
    class Meta(AbstractUser.Meta):
        constraints = [models.UniqueConstraint(Lower("username"), name="studio_username_ci_unique")]


class Preference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preference")
    theme = models.CharField(max_length=10, default="light")
    notes = models.JSONField(default=list)
    model_profile = models.CharField(max_length=10, blank=True, default="")


class Chat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=160, blank=True, default=DEFAULT_CHAT_TITLE)
    title_is_custom = models.BooleanField(default=False)
    audience = models.CharField(max_length=32, default="everyone")
    current_revision = models.ForeignKey(
        "Revision", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_publication = models.ForeignKey(
        "Publication", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Run(models.Model):
    ACTIVE = ("queued", "generating", "checking")
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="runs")
    operation = models.CharField(max_length=16)
    prompt = models.TextField()
    audience = models.CharField(max_length=32, default="everyone")
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=100, blank=True)
    model_profile = models.CharField(max_length=10, blank=True, default="")
    status = models.CharField(max_length=32, default="queued")
    stage = models.CharField(max_length=40, default="queued")
    message = models.TextField(default="В очереди на создание игры")
    idempotency_key = models.CharField(max_length=100)
    request_fingerprint = models.CharField(max_length=64)
    base_revision = models.ForeignKey("Revision", null=True, on_delete=models.SET_NULL, related_name="+")
    source_revision = models.ForeignKey("Revision", null=True, on_delete=models.SET_NULL, related_name="+")
    game_request = models.TextField(blank=True)
    generation_profile = models.CharField(max_length=16, default="full")
    source_format = models.CharField(max_length=10, default="string")
    generation_strategy = models.CharField(max_length=16, default="lite")
    planning_required = models.BooleanField(default=False)
    game_plan = models.JSONField(default=dict)
    pipeline_version = models.PositiveSmallIntegerField(default=8)
    candidate_revision = models.ForeignKey("Revision", null=True, on_delete=models.SET_NULL, related_name="+")
    result_revision = models.ForeignKey("Revision", null=True, on_delete=models.SET_NULL, related_name="+")
    continued_from = models.ForeignKey(
        "self", null=True, on_delete=models.SET_NULL, related_name="continuations"
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    max_repair_attempts = models.PositiveSmallIntegerField(default=3)
    allow_model_calls = models.BooleanField(default=True)
    completion_policy = models.PositiveSmallIntegerField(default=2)
    model_call_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    model_call_deadline = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    fence = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    error = models.JSONField(null=True)
    metrics = models.JSONField(default=dict)
    private_diagnostics = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_repair_attempts__lte=3), name="studio_run_repair_limit"
            ),
            models.UniqueConstraint(fields=["chat", "idempotency_key"], name="studio_run_idempotency"),
            models.UniqueConstraint(
                fields=["chat"],
                condition=models.Q(status__in=("queued", "generating", "checking")),
                name="studio_one_active_run",
            ),
        ]

    @property
    def max_model_calls(self):
        maximum = 1 + self.max_repair_attempts + int(self.planning_required)
        return min(maximum, self.model_call_limit) if self.model_call_limit is not None else maximum


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    run = models.ForeignKey(Run, null=True, on_delete=models.SET_NULL, related_name="chat_messages")
    role = models.CharField(max_length=16)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Revision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.SET_NULL, null=True, related_name="revisions")
    run = models.ForeignKey(Run, on_delete=models.SET_NULL, null=True, related_name="revisions")
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True)
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    files = models.JSONField()
    html = models.TextField()
    artifact_hash = models.CharField(max_length=64, db_index=True)
    file_hashes = models.JSONField(default=dict)
    design = models.JSONField(default=dict)
    checks = models.JSONField(default=list)
    diff = models.JSONField(default=list)
    checks_review_required = models.BooleanField(default=False)
    generation_profile = models.CharField(max_length=16, default="full")
    compact_manifest = models.JSONField(default=dict)
    runtime_version = models.PositiveSmallIntegerField(default=0)
    pipeline_version = models.PositiveSmallIntegerField(default=8)
    accepted = models.BooleanField(default=False)
    verification = models.CharField(max_length=16, default="none")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["chat", "number"], name="studio_revision_number")]
        ordering = ["number"]


class CheckReport(models.Model):
    validation_run = models.ForeignKey(
        "Run", null=True, on_delete=models.SET_NULL, related_name="check_reports"
    )
    revision = models.ForeignKey(Revision, on_delete=models.CASCADE, related_name="reports")
    status = models.CharField(max_length=32)
    findings = models.JSONField(default=list)
    facts = models.JSONField(default=list)
    stages = models.JSONField(default=list)
    elapsed_seconds = models.FloatField(default=0)
    environment = models.JSONField(default=dict)
    screenshot_base64 = models.TextField(blank=True)
    screenshot_mime = models.CharField(max_length=30, default="image/png")
    identity = models.CharField(max_length=64, db_index=True)
    checks = models.JSONField(default=list)
    assessment = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class Budget(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    limit_usd = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("50"))


class Invocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="invocations")
    attempt = models.PositiveSmallIntegerField()
    state = models.CharField(max_length=20, default="reserved")
    request = models.JSONField()
    response = models.JSONField(null=True)
    raw_response = models.JSONField(null=True)
    revision = models.ForeignKey(Revision, null=True, on_delete=models.SET_NULL, related_name="+")
    error = models.JSONField(null=True)
    usage = models.JSONField(null=True)
    reservation_usd = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    cost_usd = models.DecimalField(max_digits=14, decimal_places=6, null=True)
    price = models.JSONField(default=dict)
    provider_invocation_id = models.CharField(max_length=200, blank=True)
    provider_metadata = models.JSONField(default=dict)
    elapsed_seconds = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "attempt"], name="studio_invocation_attempt")]


class RunEvent(models.Model):
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=40)
    message = models.TextField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class Outbox(models.Model):
    run = models.OneToOneField(Run, on_delete=models.CASCADE)
    dispatched_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Publication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    source_chat = models.ForeignKey(Chat, on_delete=models.SET_NULL, null=True)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Like(models.Model):
    publication = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["publication", "user"], name="studio_like_unique")]


class Feedback(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    revision = models.ForeignKey(Revision, on_delete=models.SET_NULL, null=True)
    rating = models.PositiveSmallIntegerField()
    reasons = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5), name="studio_feedback_range"
            )
        ]
