# Agentic Board Implementation Plans

These plans expand Section 12 of `docs/AGENTIC_BOARD_V2_GUIDEBOOK.md` into
phase-by-phase implementation notes.

Use them as hardening guides, not as permission to rewrite working modules. The
current project already implements much of the Phase 0-10 architecture. Each
phase should preserve the simplest working contract and add complexity only
after live board sessions prove the simple path is failing.

Phase index:

- `phase0_output_format_and_member_template.md`
- `phase1_infrastructure.md`
- `phase2_first_member.md`
- `phase3_full_council.md`
- `phase4_context_compaction.md`
- `phase5_adaptive_routing.md`
- `phase6_institutional_memory.md`
- `phase7_verification_layer.md`
- `phase8_error_handling.md`
- `phase9_cli_api_polish.md`
- `phase10_business_growth_extensions.md`

Working rule:

```text
One small contract, one implementation path, one verification path.
No framework unless repeated real use proves the simple version is failing.
```
