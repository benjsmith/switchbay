"""Tiny orchestrator kernel: hire, desk lifetime, harness plugs.

The kernel is not the rail chat partner. It seats a chief on the rail
picker, prices extra specialists, and stands a desk down only on Stop.
"""

from .desk import (
    DESK_AUTO,
    DESK_CODE,
    DESK_CURATE,
    DESK_PROJECTS,
    STATE_DISMISSED,
    STATE_QUIET,
    STATE_WORKING,
    DeskRecord,
    dismiss,
    dismiss_run,
    get,
    quiet,
    seat,
    set_working,
    window_ended,
)
from .harness import NodeRequest, NodeResult, pi_available, pick_harness, run_node
from .hire import (
    HireDecision, HireRequest, decide_hire, pick_family_hires,
    pick_critic_model, pick_kernel_model, pick_worker_model,
)
from .packages import (
    CODE_EDIT_ID, CODE_EXPLORE_ID, CODE_PLAN_ID, CODE_REVIEW_ID,
    CODING_FAMILY, CURATOR_ID, ORG_SYSTEMS_ID, PORTFOLIO_BALANCE_ID,
    PROJECT_COMMS_ID, PROJECT_PLAN_ID, PROJECT_REVIEW_ID, PROJECT_SENSE_ID,
    PROJECTS_FAMILY, RESEARCH_ID, SLIDESHOW_ID, Package, family_ids,
    get_package, packages_for_desk,
)

__all__ = [
    "CODE_EDIT_ID",
    "CODE_EXPLORE_ID",
    "CODE_PLAN_ID",
    "CODE_REVIEW_ID",
    "CODING_FAMILY",
    "CURATOR_ID",
    "ORG_SYSTEMS_ID",
    "PORTFOLIO_BALANCE_ID",
    "PROJECT_COMMS_ID",
    "PROJECT_PLAN_ID",
    "PROJECT_REVIEW_ID",
    "PROJECT_SENSE_ID",
    "PROJECTS_FAMILY",
    "RESEARCH_ID",
    "SLIDESHOW_ID",
    "DESK_AUTO",
    "DESK_CODE",
    "DESK_CURATE",
    "DESK_PROJECTS",
    "STATE_DISMISSED",
    "STATE_QUIET",
    "STATE_WORKING",
    "DeskRecord",
    "HireDecision",
    "HireRequest",
    "NodeRequest",
    "NodeResult",
    "Package",
    "decide_hire",
    "family_ids",
    "packages_for_desk",
    "pick_family_hires",
    "pick_critic_model",
    "dismiss",
    "dismiss_run",
    "get",
    "get_package",
    "pi_available",
    "pick_harness",
    "pick_kernel_model",
    "pick_worker_model",
    "quiet",
    "run_node",
    "seat",
    "set_working",
    "window_ended",
]
