from __future__ import annotations

import inspect

import migrations.versions.f4d9c2a7b310_design_partner_retention_ceiling as migration


def test_aggregate_lock_function_is_narrow_and_least_privilege() -> None:
    source = inspect.getsource(migration.upgrade)

    assert "CREATE FUNCTION ai_fde_lock_design_partner_authority" in source
    function_source = source.split(
        "CREATE FUNCTION ai_fde_lock_design_partner_authority",
        maxsplit=1,
    )[1]
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, public" in source
    assert "SET row_security = off" in source
    assert "session_user = 'ai_fde_app'" in source
    assert "caller_operator.is_active = true" in source
    assert "membership.role IN ('owner', 'operator', 'viewer')" in source
    assert "required_access NOT IN ('read', 'write')" in source
    assert "required_access = 'read'" in source
    assert "membership.role IN ('owner', 'operator')" in source
    assert "FOR SHARE OF caller_operator, membership" in source
    assert "session_user ~ '^ai_fde_worker_[0-9a-f]{12}$'" in source
    assert "public.ai_fde_worker_can_access_engagement(target_engagement_id)" in source
    assert function_source.index("FROM public.engagements AS engagement") < function_source.index(
        "FROM public.design_partner_qualifications AS qualification"
    )
    assert (
        "REVOKE ALL ON FUNCTION ai_fde_lock_design_partner_authority(uuid, text) FROM PUBLIC"
        in source
    )
    assert (
        "ai_fde_lock_design_partner_authority(uuid, text) TO ai_fde_app"
        in source
    )
    assert "TO ai_fde_worker" in source
    assert "GRANT UPDATE" not in source
    assert "EXECUTE '" not in source
