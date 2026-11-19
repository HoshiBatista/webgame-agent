"""Select distinct mechanics from comparable published games without an LLM call."""

import re

from django.db.models import Count, F, Q, Sum

from generation.schema import CONTRACT_VERSION

from .models import PlaySession, Publication, PublicationRating

# A specific genre takes precedence over the theme of an open-ended request.
GENRES = {
    "snake": r"\b(?:змейк|snake\b)",
    "puzzle": r"\b(?:головолом|пазл|puzzl|сокобан|sokoban)",
    "shooter": r"\b(?:шутер|стрелялк|shoot(?:er|[ -]em[ -]up))",
    "platformer": r"\b(?:платформер|platformer)",
    "rpg": r"\b(?:рпг\b|rpg\b|ролев\w*\s+игр)",
    "racing": r"\b(?:гонк|гоноч|racing\b)",
    "runner": r"\b(?:раннер|runner\b)",
    "arcade": r"\b(?:аркад|arcade\b)",
}
OPEN_SPACE_GAME = re.compile(
    r"(?:(?:сделай|создай|сгенерируй|хочу)\s+)?(?:"
    r"(?:мини[- ]?)?игр[ау]\s+(?:про космос|о космосе|в космосе)|космическ(?:ую|ая)\s+игр[ау])"
    r"|(?:(?:make|create|generate)\s+)?(?:a\s+)?space(?:-themed)?\s+game"
)
# A keyboard instruction such as "press Space" is not evidence about the theme.
SPACE_SETTING = re.compile(r"\b(?:космос|космич|звездолет|астероид|spaceship|asteroid|outer space|space (?:shooter|flight|station|exploration))")
# Only these authored suggestions can leave this module. Never interpolate the source
# title, plan, author notes or public game code into another user's model request.
HINTS = {
    "enemy_waves": (
        r"\b(?:волн\w*\s+(?:враг|противник|монстр|атак)|(?:enemy\s+waves?|waves?\s+of\s+enem))",
        "Если это подходит игре, дай игроку освоить первую волну противников до появления следующей.",
    ),
    "optional_clue": (
        r"\b(?:подсказк|hints?\b|clues?\b)",
        "Подумай о подсказке к следующему действию, которую игрок может запросить сам.",
    ),
    "checkpoint": (
        r"\b(?:контрольн\w*\s+точк|чекпоинт|checkpoints?\b)",
        "Рассмотри контрольную точку перед сложным участком, чтобы игрок мог быстро его повторить.",
    ),
    "resource_upgrade": (
        r"\b(?:улучш\w*\s+за\s+(?:ресурс|монет)|(?:монет|ресурс)\w*\s+на\s+улучш|spend\s+coins\s+on\s+upgrades?)",
        "Если уместно, предложи потратить собранный ресурс на одно улучшение с заметным игровым эффектом.",
    ),
    "route_choice": (
        r"\b(?:развилк|выбор\s+маршрут|branching\s+(?:route|path))",
        "Рассмотри развилку, где выбор пути меняет ближайшее испытание.",
    ),
}
RESTRICTION = re.compile(r"\b(?:без|не|никак\w*|только|исключительно|without|never|no|not|only)\b")
MAX_CANDIDATES = 100
MAX_HINTS = 3
MIN_SESSIONS = 8
MIN_RATINGS = 3


def _genres(text):
    return {key for key, pattern in GENRES.items() if re.search(pattern, text)}


def _source_hint_keys(row, requested_genres, available_patterns):
    # Read selected design fields only, never the original/private request or transcript.
    descriptions = [row["revision__design__summary"], row["revision__run__game_plan__summary"]]
    mechanics = row["revision__run__game_plan__mechanics"]
    descriptions.extend(mechanics[:4] if isinstance(mechanics, list) else [])
    descriptions += [row["revision__run__game_plan__core_loop"], row["revision__run__game_plan__progression"]]
    fields = [text.casefold() for text in descriptions if isinstance(text, str) and not RESTRICTION.search(text.casefold())]
    if requested_genres:
        if not requested_genres.issubset(_genres(" ".join([row["title"].casefold(), *fields]))):
            return []
    elif not any(SPACE_SETTING.search(field) for field in fields):
        return []
    return [key for key, pattern in available_patterns if any(re.search(pattern, field) for field in fields)]


def choose_analytics_hints(*, prompt, audience):
    """Return up to three distinct hints and the strongest source snapshot for each."""
    from .publication_analytics import MIN_AVERAGED_SESSION_MS

    prompt = prompt.casefold()
    genres = _genres(prompt)
    if RESTRICTION.search(prompt) or (not genres and not OPEN_SPACE_GAME.fullmatch(prompt.strip(" .!?\t\r\n"))):
        return []
    # A mechanic already requested by the author belongs in every variant.
    available_patterns = [(key, pattern) for key, (pattern, _) in HINTS.items() if not re.search(pattern, prompt)]
    if not available_patterns:
        return []

    recent = Publication.objects.filter(
        unavailable_at__isnull=True, revision__pipeline_version=CONTRACT_VERSION, revision__run__audience=audience,
    ).order_by("-created_at", "pk").values(
        "pk", "title", "revision_id", "revision__artifact_hash", "revision__design__summary",
        "revision__run__game_plan__summary", "revision__run__game_plan__core_loop",
        "revision__run__game_plan__mechanics", "revision__run__game_plan__progression",
    )[:MAX_CANDIDATES]
    candidates = {
        row["pk"]: (row, keys) for row in recent if (keys := _source_hint_keys(row, genres, available_patterns))
    }
    if not candidates:
        return []

    # Independent grouped queries avoid multiplying sessions by the number of ratings.
    sessions = PlaySession.objects.filter(
        publication_id__in=candidates, revision_id_snapshot=F("publication__revision_id"),
        artifact_hash=F("publication__revision__artifact_hash"),
    ).values("publication_id", "revision_id_snapshot", "artifact_hash").annotate(
        n=Count("pk"), engaged=Count("pk", filter=Q(visible_ms__gte=MIN_AVERAGED_SESSION_MS)),
    ).filter(n__gte=MIN_SESSIONS)
    activity = {
        (s["publication_id"], s["revision_id_snapshot"], s["artifact_hash"]): s
        for s in sessions if s["engaged"] * 2 >= s["n"]
    }
    if not activity:
        return []

    # Ratings belong to a publication. Counting only votes cast/updated since its
    # last change conservatively discards ratings left on a previous revision.
    ratings = PublicationRating.objects.filter(
        publication_id__in=candidates, publication__unavailable_at__isnull=True,
        updated_at__gte=F("publication__updated_at"),
    ).values("publication_id", "publication__revision_id").annotate(
        n=Count("pk"), stars=Sum("rating"),
    ).filter(n__gte=MIN_RATINGS)
    ranked_sources = []
    for rating in ratings:
        publication_id = rating["publication_id"]
        row, keys = candidates[publication_id]
        version = row["revision_id"]
        session = activity.get((publication_id, version, row["revision__artifact_hash"]))
        if not session or rating["publication__revision_id"] != version:
            continue
        # A neutral prior equivalent to three 3-star votes tempers small samples.
        adjusted_rating = (rating["stars"] + 9) / (rating["n"] + 3)
        if adjusted_rating < 3.5:
            continue
        score = (adjusted_rating, session["engaged"] / session["n"], rating["n"], publication_id)
        evidence = {
            "source_publication_id": str(publication_id), "source_revision_id": str(version),
            "source_artifact_hash": row["revision__artifact_hash"],
            "match_basis": "genre" if genres else "theme",
            "genre": sorted(genres)[0] if genres else None, "theme": None if genres else "space",
            "ratings_count": rating["n"], "rating_mean": round(rating["stars"] / rating["n"], 2),
            "sessions_count": session["n"], "engaged_sessions": session["engaged"],
        }
        ranked_sources.append((score, keys, evidence))

    # Publications with identical rates have a stable ID tie-break. Mechanics
    # within a publication retain catalogue order, independent of SQL row order.
    hints = {}
    for _, keys, evidence in sorted(ranked_sources, key=lambda source: source[0], reverse=True):
        for key in keys:
            if key not in hints:
                hints[key] = {"hint_key": key, "text": HINTS[key][1], **evidence}
    return list(hints.values())[:MAX_HINTS]
