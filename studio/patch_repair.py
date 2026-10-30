"""Select a bounded fragment correction from a durably settled edit receipt."""

from copy import deepcopy

from generation.errors import ContractError
from generation.patch_repair import REPAIRABLE, permission

from .continuations import lineage_ids
from .models import Invocation


def pending_permission(run, base):
    previous = None
    for ident in lineage_ids(run):
        previous = Invocation.objects.filter(run_id=ident).order_by("-attempt").first()
        if previous is not None:
            break
    if (previous is None or previous.revision_id or previous.state not in {"settled", "failed"}
            or not previous.error
            or previous.request.get("operation") != "edit"
            or previous.request.get("base_revision") != str(base.id)):
        return None
    profile = previous.request.get("generation_profile", "full")
    prior = previous.request.get("patch_repair")
    response = previous.response
    if prior:
        # Keep the original scope after *any* rejected correction. In particular,
        # a new overlap must not grant permission to rewrite a previously good slot.
        return deepcopy(prior)
    elif previous.error.get("code") not in REPAIRABLE or not response:
        return None
    try:
        return permission(response, files=base.files, base_revision=base.id, profile=profile)
    except ContractError:
        return None
